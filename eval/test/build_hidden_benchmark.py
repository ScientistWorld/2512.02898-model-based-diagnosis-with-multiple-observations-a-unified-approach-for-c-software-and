#!/usr/bin/env python3
"""Packaging-time builder for the circuit-diagnosis gym (lives only in eval/test).

Not used for scoring.  Run once (by scripts/run.sh during packaging) to:

  build       generate the public train split (public seed in
              data/circuit_benchmark.py) and the hidden test split (secret
              seed below) from the ISCAS85 netlists, and compute the exact
              answer of every instance: the minimum diagnosis cardinality k*
              (MaxSAT, RC2) and the complete set of minimum-cardinality
              diagnoses (SAT enumeration under an at-most-k* cardinality
              constraint, blocking each solution).  The answer is checked
              independently: "at most k*-1" must be UNSAT and sampled
              diagnoses are re-validated by bit-parallel simulation.
              Instances whose answer cannot be enumerated within the offline
              limits are resampled (next attempt index of the same cell); a
              cell with no acceptable attempt is skipped.  Cells are solved in
              parallel and the split is saved as it grows (resumable).
  budget      choose the per-instance instruction budget from the reference
              method's behaviour on the PUBLIC train split only.
  baselines   run the HSD and BugAssist-vote baselines through both evaluators
              and store their raw outputs (evaluator-owned baseline results).

Test answers and the code/seed that regenerates them live only in eval/test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import random
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from data.circuit_benchmark import (  # noqa: E402
    ATTEMPT_STRIDE,
    CIRCUITS,
    GROUND_TRUTH_FILE,
    INSTANCES_FILE,
    STRESS_CIRCUITS,
    TRAIN_SEED,
    BASE_SLOTS,
    STRESS_SLOTS,
    cell_key,
    circuit_from_json,
    diagnosis_semantically_valid,
    grid,
    load_iscas85,
    make_instance,
    read_json,
    read_jsonl,
    split_cells,
    stress_grid,
    write_json,
    write_jsonl,
)

BENCHMARK_VERSION = 3
HIDDEN_SEED = "cfaults-hidden-test-v3-039d3f4c8804770feb82c411956b956e8aa30464d38b862f"
BENCH_DIR = REPO_ROOT / "data" / "downloads" / "iscas85"
TEST_FILE = HERE / "hidden_benchmark.json.gz"
TRAIN_DIR = REPO_ROOT / "data" / "iscas85_train"
TEST_CONFIG = HERE / "config.json"
TRAIN_CONFIG = REPO_ROOT / "eval" / "train" / "config.json"
MAX_DIAGNOSES = {"base": 4000, "stress": 4000}
GT_CPU_BUDGET = {"base": 90.0, "stress": 120.0}
MAX_ATTEMPTS = {"base": 3, "stress": 2}
BUILD_DEADLINE_SECONDS = {"train": 40 * 60, "test": 80 * 60}  # remaining cells are skipped after it

# Per-instance budget: user-space instructions retired by the method's process tree.
BUDGET_VERSION = 1
BUDGET_CANDIDATES = tuple(int(x * 1e9) for x in (5, 7.5, 10, 15, 20, 25, 30, 40, 50, 60))
PROBE_CAP = int(80e9)
TARGET_MAX_TRAIN_COVERAGE = 75.0
BUDGET_FRACTIONS = {"half_budget": 0.5, "quarter_budget": 0.25, "eighth_budget": 0.125}
WALL_LIMIT_SECONDS = 240.0
DEFAULT_FALLBACK_RATE = 5e9  # instructions per CPU-second; replaced by the probe's measured rate


def log(msg: str) -> None:
    print(f"[builder] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Exact answers
# --------------------------------------------------------------------------


def guarded(op: str, out: int, ins: list[int], h: int) -> list[list[int]]:
    g = -h
    if op == "BUF":
        return [[g, -out, ins[0]], [g, out, -ins[0]]]
    if op == "NOT":
        return [[g, -out, -ins[0]], [g, out, ins[0]]]
    if op == "AND":
        return [[g, out, *[-x for x in ins]], *[[g, -out, x] for x in ins]]
    if op == "NAND":
        return [[g, -out, *[-x for x in ins]], *[[g, out, x] for x in ins]]
    if op == "OR":
        return [[g, -out, *ins], *[[g, out, -x] for x in ins]]
    if op == "NOR":
        return [[g, out, *ins], *[[g, -out, -x] for x in ins]]
    if op == "XOR":
        a, b = ins
        return [[g, -a, -b, -out], [g, -a, b, out], [g, a, -b, out], [g, a, b, -out]]
    raise ValueError(op)


def encode(circuit: dict, observations: list[dict]) -> tuple[list[list[int]], dict[str, int], int]:
    nv = 0
    health: dict[str, int] = {}
    for gate in circuit["gates"]:
        nv += 1
        health[gate["name"]] = nv
    clauses: list[list[int]] = []
    for obs in observations:
        var: dict[str, int] = {}
        for name in circuit["inputs"]:
            nv += 1
            var[name] = nv
            clauses.append([nv if obs["inputs"][name] else -nv])
        for gate in circuit["gates"]:
            nv += 1
            var[gate["name"]] = nv
        for gate in circuit["gates"]:
            clauses.extend(guarded(gate["op"], var[gate["name"]], [var[x] for x in gate["inputs"]], health[gate["name"]]))
        for name, value in obs["expected_outputs"].items():
            clauses.append([var[name] if value else -var[name]])
    return clauses, health, nv


def exact_answer(instance: dict, cpu_budget: float = 150.0, max_diagnoses: int = 4000) -> dict:
    from pysat.card import CardEnc, EncType
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF
    from pysat.solvers import Solver

    t0 = time.process_time()
    circuit, observations = instance["circuit"], instance["observations"]
    clauses, health, nv = encode(circuit, observations)
    wcnf = WCNF()
    for clause in clauses:
        wcnf.append(clause)
    for lit in health.values():
        wcnf.append([lit], weight=1)
    with RC2(wcnf) as rc2:
        model = rc2.compute()
        if model is None:
            raise RuntimeError("hard clauses unsatisfiable")
        assigned = set(model)
        k = sum(1 for lit in health.values() if -lit in assigned)
    unhealthy = [-lit for lit in health.values()]
    if k > 0:
        if k == 1:
            lower_clauses = [[lit] for lit in health.values()]  # at most 0 unhealthy gates
        else:
            lower_clauses = CardEnc.atmost(lits=unhealthy, bound=k - 1, top_id=nv, encoding=EncType.seqcounter).clauses
        with Solver(name="g4", bootstrap_with=clauses + lower_clauses) as sat:
            if sat.solve():
                raise RuntimeError("optimum is not minimal: at-most-(k-1) is satisfiable")
    card = CardEnc.atmost(lits=unhealthy, bound=k, top_id=nv, encoding=EncType.seqcounter)
    diagnoses: list[list[str]] = []
    status = "complete"
    with Solver(name="g4", bootstrap_with=clauses + card.clauses) as sat:
        while sat.solve():
            assigned = set(sat.get_model())
            diag = sorted(name for name, lit in health.items() if -lit in assigned)
            if len(diag) != k:
                raise RuntimeError("enumerated diagnosis of the wrong size")
            diagnoses.append(diag)
            if len(diagnoses) > max_diagnoses:
                status = "too_many"
                break
            if time.process_time() - t0 > cpu_budget:
                status = "too_slow"
                break
            sat.add_clause([health[name] for name in diag])
    return {"optimum": k, "diagnoses": diagnoses, "status": status, "cpu_seconds": time.process_time() - t0}


def exact_answer_limited(instance: dict, cpu_budget: float, max_diagnoses: int) -> dict:
    """exact_answer in a child process with a hard CPU limit on EVERY step
    (MaxSAT optimum, lower-bound proof, enumeration); a kill means too_slow."""
    hard = int(cpu_budget) + 30
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = Path(tmp) / "instance.json", Path(tmp) / "answer.json"
        inp.write_text(json.dumps(instance))

        def limit() -> None:
            resource.setrlimit(resource.RLIMIT_CPU, (hard, hard + 1))

        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "exact", "--instance", str(inp),
                               "--answer", str(out), "--budget", str(cpu_budget), "--max-diagnoses", str(max_diagnoses)],
                              cwd=REPO_ROOT, preexec_fn=limit, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            killed = proc.returncode < 0 or "RuntimeError" not in proc.stderr
            return {"optimum": None, "diagnoses": [], "status": "too_slow" if killed else "error",
                    "cpu_seconds": float(hard), "stderr": proc.stderr[-500:]}
        return json.loads(out.read_text())


def verify_answer(instance: dict, answer: dict, rng: random.Random) -> None:
    circuit = circuit_from_json(instance["circuit"])
    obs = instance["observations"]
    if not diagnosis_semantically_valid(circuit, obs, instance["faults"]):
        raise RuntimeError("injected fault set does not explain the observations")
    if answer["optimum"] > len(instance["faults"]):
        raise RuntimeError("optimum larger than injected fault count")
    sample = answer["diagnoses"] if len(answer["diagnoses"]) <= 20 else rng.sample(answer["diagnoses"], 20)
    for diag in sample:
        if not diagnosis_semantically_valid(circuit, obs, diag):
            raise RuntimeError(f"enumerated diagnosis {diag} fails simulation check")
    if len({tuple(d) for d in answer["diagnoses"]}) != len(answer["diagnoses"]):
        raise RuntimeError("duplicate diagnoses in answer")


# --------------------------------------------------------------------------
# Building the splits (parallel over cells, resumable)
# --------------------------------------------------------------------------

_CIRCUIT_CACHE: dict = {}


def _golden(name: str):
    if name not in _CIRCUIT_CACHE:
        _CIRCUIT_CACHE[name] = load_iscas85(BENCH_DIR, name)
    return _CIRCUIT_CACHE[name]


def solve_cell(task: tuple[str, str, tuple]) -> dict:
    """First acceptable attempt of one cell (worker process)."""
    split, seed_text, cell = task
    tier, circuit_name, k, m, slot = cell
    key = cell_key(*cell)
    rng = random.Random(f"verify|{seed_text}|{key}")
    rejected = []
    first = slot * ATTEMPT_STRIDE
    for attempt in range(first, first + MAX_ATTEMPTS[tier]):
        inst = make_instance(_golden(circuit_name), split, seed_text, k, m, attempt, tier)
        if inst is None:
            rejected.append({"cell": key, "attempt": attempt, "reason": "no_failing_observations"})
            continue
        answer = exact_answer_limited(inst, GT_CPU_BUDGET[tier], MAX_DIAGNOSES[tier])
        if answer["status"] != "complete":
            rejected.append({"cell": key, "attempt": attempt, "reason": answer["status"],
                             "optimum": answer["optimum"], "partial_count": len(answer["diagnoses"]),
                             **({"stderr": answer["stderr"]} if answer["status"] == "error" else {})})
            continue
        try:
            verify_answer(inst, answer, rng)
        except RuntimeError as exc:  # never expected; recorded for inspection, the attempt is not used
            rejected.append({"cell": key, "attempt": attempt, "reason": f"verification_failed: {exc}"})
            continue
        return {"cell": key, "attempt": attempt, "instance": inst, "rejected": rejected,
                "truth": {"optimum": answer["optimum"], "diagnoses": answer["diagnoses"],
                          "enumeration_cpu_seconds": round(answer["cpu_seconds"], 3)}}
    return {"cell": key, "attempt": None, "instance": None, "rejected": rejected, "truth": None}


def _load_state(split: str) -> dict:
    empty = {"version": BENCHMARK_VERSION, "instances": [], "ground_truth": {}, "accepted_attempts": {},
             "rejected_attempts": [], "skipped_cells": {}}
    if split == "test":
        state = read_json(TEST_FILE) if TEST_FILE.exists() else None
    else:
        manifest_path = TRAIN_DIR / "manifest.json"
        state = None
        if manifest_path.exists() and (TRAIN_DIR / INSTANCES_FILE).exists() and (TRAIN_DIR / GROUND_TRUTH_FILE).exists():
            state = json.loads(manifest_path.read_text())
            state["instances"] = read_jsonl(TRAIN_DIR / INSTANCES_FILE)
            state["ground_truth"] = read_json(TRAIN_DIR / GROUND_TRUTH_FILE)
    if not state or state.get("version") != BENCHMARK_VERSION:
        return empty
    return state


def _save_state(split: str, state: dict) -> None:
    order = {cell_key(*c): i for i, c in enumerate(split_cells(split))}

    def rank(inst):
        return order.get(cell_key(inst["tier"], inst["source_circuit"], inst["fault_count"], inst["observation_count"],
                                  inst["attempt"] // ATTEMPT_STRIDE), 10 ** 9)

    state["instances"].sort(key=rank)
    if split == "test":
        write_json(TEST_FILE, state)
        return
    write_jsonl(TRAIN_DIR / INSTANCES_FILE, state["instances"])
    write_json(TRAIN_DIR / GROUND_TRUTH_FILE, state["ground_truth"])
    manifest = {k: v for k, v in state.items() if k not in ("instances", "ground_truth")}
    manifest.update({
        "name": "iscas85_multi_observation_diagnosis_train",
        "source": "ISCAS85 .bench netlists (scripts/download.sh), gate-type fault injection",
        "circuits": list(CIRCUITS), "stress_circuits": list(STRESS_CIRCUITS),
        "grid": [list(cell) for cell in grid()], "base_slots": BASE_SLOTS["train"],
        "stress_grid": [list(cell) for cell in stress_grid(STRESS_SLOTS["train"])],
        "seed": TRAIN_SEED, "instance_count": len(state["instances"]),
        "files": {"instances": INSTANCES_FILE, "ground_truth": GROUND_TRUTH_FILE},
        "limits": {"max_minimum_diagnoses": MAX_DIAGNOSES, "offline_cpu_seconds": GT_CPU_BUDGET,
                   "attempts_per_cell": MAX_ATTEMPTS},
    })
    (TRAIN_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def build_split(split: str, workers: int) -> None:
    seed_text = HIDDEN_SEED if split == "test" else TRAIN_SEED
    state = _load_state(split)
    done = set(state["accepted_attempts"]) | set(state["skipped_cells"])
    todo = [c for c in split_cells(split) if cell_key(*c) not in done]
    # fixed pseudo-random order: if the deadline is hit, skipped cells are spread over tiers and circuits
    todo.sort(key=lambda c: hashlib.sha256(f"order|{split}|{cell_key(*c)}".encode()).hexdigest())
    log(f"{split}: {len(state['instances'])} instances present, {len(todo)} cells to build with {workers} workers")
    if not todo:
        _save_state(split, state)
        return
    deadline = time.monotonic() + BUILD_DEADLINE_SECONDS[split]
    last_save = time.monotonic()
    pool = multiprocessing.get_context("fork").Pool(workers)
    finished = set()
    try:
        for res in pool.imap_unordered(solve_cell, [(split, seed_text, c) for c in todo]):
            finished.add(res["cell"])
            state["rejected_attempts"] += res["rejected"]
            if res["instance"] is None:
                state["skipped_cells"][res["cell"]] = "no attempt enumerable offline"
                log(f"{split} {res['cell']}: skipped ({[r['reason'] for r in res['rejected']]})")
            else:
                inst = res["instance"]
                state["instances"].append(inst)
                state["ground_truth"][inst["id"]] = res["truth"]
                state["accepted_attempts"][res["cell"]] = res["attempt"]
                log(f"{split} {res['cell']} attempt {res['attempt']}: k*={res['truth']['optimum']} "
                    f"#min={len(res['truth']['diagnoses'])} ({res['truth']['enumeration_cpu_seconds']:.1f}s)")
            if time.monotonic() - last_save > 60:
                _save_state(split, state)
                last_save = time.monotonic()
            if time.monotonic() > deadline:
                log(f"{split}: build deadline reached")
                break
    finally:
        pool.terminate()
        pool.join()
    for c in todo:
        key = cell_key(*c)
        if key not in finished:
            state["skipped_cells"][key] = "build deadline"
    _save_state(split, state)
    log(f"{split}: {len(state['instances'])} instances, {len(state['skipped_cells'])} skipped cells")


def phase_build(splits: list[str], workers: int) -> None:
    for split in splits:
        build_split(split, workers)


# --------------------------------------------------------------------------
# Budget (from the public train split only)
# --------------------------------------------------------------------------


def evaluator(split: str) -> str:
    return f"eval/{split}/evaluate_circuit_outputs.py"


def default_config() -> dict:
    return {
        "instruction_budget": float(BUDGET_CANDIDATES[len(BUDGET_CANDIDATES) // 2]),
        "budget_fractions": BUDGET_FRACTIONS,
        "wall_limit_seconds": WALL_LIMIT_SECONDS,
        "fallback_instructions_per_cpu_second": DEFAULT_FALLBACK_RATE,
        "required_methods": ["cfaults"],
    }


def ensure_configs() -> None:
    for path in (TEST_CONFIG, TRAIN_CONFIG):
        cfg = json.loads(path.read_text()) if path.exists() else {}
        if "instruction_budget" not in cfg:
            cfg = default_config()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")


def _credited_at(record: dict, budget: float) -> list:
    n = 0
    for count, k in record.get("line_trace") or []:
        if count <= budget and k > n:
            n = k
    return list(record.get("diagnoses") or [])[:n]


def _localized_at(record: dict, truth_entry: dict, budget: float) -> bool:
    if record.get("truncated"):
        return False
    lines = _credited_at(record, budget)
    if not all(isinstance(d, list) and all(isinstance(x, str) for x in d) for d in lines):
        return False
    got = [frozenset(d) for d in lines]
    expected = {frozenset(d) for d in truth_entry["diagnoses"]}
    return len(got) == len(set(got)) == len(expected) and set(got) == expected


def phase_budget() -> None:
    ensure_configs()
    tcfg = json.loads(TRAIN_CONFIG.read_text())
    if tcfg.get("budget_selection", {}).get("version") == BUDGET_VERSION:
        log("budget already selected")
        return
    reg = REPO_ROOT / "checkpoints" / "cfaults_circuit" / "solver.json"
    if not reg.exists():
        subprocess.run([sys.executable, "method/cfaults_circuit.py", "--register"], cwd=REPO_ROOT, check=True)
    probe_runs = REPO_ROOT / "eval" / "train" / "runs" / "budget_probe.json.gz"
    if not probe_runs.exists():
        subprocess.run([sys.executable, "-I", evaluator("train"), "--instruction-cap", str(PROBE_CAP), "--methods",
                        "cfaults", "--runs-name", "budget_probe", "--out", str(REPO_ROOT / "tmp" / "budget_probe_scores.json")],
                       cwd=REPO_ROOT, check=True)
    payload = read_json(probe_runs)
    records = {r["id"]: r for r in payload["records"]}
    instances, truth = read_jsonl(TRAIN_DIR / INSTANCES_FILE), read_json(TRAIN_DIR / GROUND_TRUTH_FILE)
    tiers = {"base": [i for i in instances if i["tier"] == "base"], "stress": [i for i in instances if i["tier"] == "stress"],
             "all": instances}
    coverage = {}
    for b in BUDGET_CANDIDATES + (PROBE_CAP,):
        coverage[f"{b / 1e9:g}G"] = {
            tier: 100.0 * sum(1 for i in group if _localized_at(records.get(i["id"], {}), truth[i["id"]], b)) / max(1, len(group))
            for tier, group in tiers.items()}
    eligible = [b for b in BUDGET_CANDIDATES if coverage[f"{b / 1e9:g}G"]["base"] <= TARGET_MAX_TRAIN_COVERAGE]
    chosen = max(eligible) if eligible else min(BUDGET_CANDIDATES)
    finished = [r for r in payload["records"] if r.get("status") == "ok" and r.get("cpu_seconds", 0) > 0.2
                and r.get("accounting") == "perf"]
    rate = (sum(r["instructions"] for r in finished) / sum(r["cpu_seconds"] for r in finished)) if finished else DEFAULT_FALLBACK_RATE
    selection = {
        "version": BUDGET_VERSION,
        "rule": f"largest candidate budget at which the reference localises <= {TARGET_MAX_TRAIN_COVERAGE}% of the "
                "public TRAIN base tier (at least a quarter of the main tier left unsolved: headroom); "
                "smallest candidate if none",
        "candidates_giga_instructions": [b / 1e9 for b in BUDGET_CANDIDATES],
        "probe_cap_giga_instructions": PROBE_CAP / 1e9,
        "train_reference_coverage_pct": coverage,
        "chosen_giga_instructions": chosen / 1e9,
        "fallback_rate_note": "instructions per CPU-second of the reference on the train probe (used only if the "
                              "hidden-test machine has no hardware instruction counter)",
    }
    for path in (TRAIN_CONFIG, TEST_CONFIG):
        c = json.loads(path.read_text())
        c["instruction_budget"] = float(chosen)
        c["budget_fractions"] = BUDGET_FRACTIONS
        c["wall_limit_seconds"] = WALL_LIMIT_SECONDS
        c["fallback_instructions_per_cpu_second"] = round(rate, -6)
        c["budget_selection"] = selection
        path.write_text(json.dumps(c, indent=2, sort_keys=True) + "\n")
    log(f"chosen budget {chosen / 1e9:g}G instructions; train coverage {json.dumps(coverage)}; fallback rate {rate:.3g}/s")


# --------------------------------------------------------------------------
# Evaluator-owned baselines
# --------------------------------------------------------------------------

BASELINES = {
    "hsd": ["python", "baseline/hsd_circuit.py", "--instance", "{instance}", "--output", "{output}"],
    "bugassist_vote": ["python", "baseline/bugassist_vote_circuit.py", "--instance", "{instance}", "--output", "{output}"],
}


def phase_baselines(splits: list[str]) -> None:
    """Store the evaluator-owned baseline outputs.

    Train-side runs go in parallel.  Test-side runs go one after another: two
    hidden-test evaluators in the same workspace would each lock eval/test and
    see the other's lock as tampering.
    """
    (REPO_ROOT / "logs").mkdir(exist_ok=True)

    def launch(split: str, name: str, command: list[str]):
        target = REPO_ROOT / "eval" / split / "baseline_outputs" / f"{name}.json.gz"
        if target.exists():
            return None
        log(f"running baseline {name} on {split}")
        logf = open(REPO_ROOT / "logs" / f"baseline_{name}_{split}.log", "w")
        proc = subprocess.Popen([sys.executable, "-I", evaluator(split), "--store-baseline", name,
                                 "--command-json", json.dumps(command)], cwd=REPO_ROOT, stdout=logf,
                                stderr=subprocess.STDOUT)
        return name, split, proc, logf

    def finish(item) -> None:
        if item is None:
            return
        name, split, proc, logf = item
        rc = proc.wait()
        logf.close()
        if rc != 0:
            raise RuntimeError(f"baseline {name} on {split} failed (rc={rc})")

    running = [launch("train", n, c) for n, c in BASELINES.items()] if "train" in splits else []
    if "test" in splits:
        for name, command in BASELINES.items():
            finish(launch("test", name, command))
    for item in running:
        finish(item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=["build", "budget", "baselines", "exact"])
    parser.add_argument("--split", choices=["train", "test", "all"], default="all")
    parser.add_argument("--workers", type=int, default=max(1, len(os.sched_getaffinity(0))))
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--answer", type=Path)
    parser.add_argument("--budget", type=float, default=150.0)
    parser.add_argument("--max-diagnoses", type=int, default=4000)
    args = parser.parse_args()
    os.chdir(REPO_ROOT)
    if args.phase == "exact":  # internal: one bounded exact computation (see exact_answer_limited)
        answer = exact_answer(json.loads(args.instance.read_text()), args.budget, args.max_diagnoses)
        args.answer.write_text(json.dumps(answer))
        return
    log(f"phase {args.phase}")
    if args.phase == "build":
        phase_build(["train", "test"] if args.split == "all" else [args.split], args.workers)
    elif args.phase == "budget":
        phase_budget()
    else:
        phase_baselines(["train", "test"] if args.split == "all" else [args.split])


if __name__ == "__main__":
    main()
