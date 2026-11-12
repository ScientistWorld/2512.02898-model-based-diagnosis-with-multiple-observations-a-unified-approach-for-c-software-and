#!/usr/bin/env python3
"""Packaging-time builder for the circuit-diagnosis gym (lives only in eval/test).

Not used for scoring.  Run once (by scripts/run.sh during packaging) to:

  build       generate the hidden test split (secret seed below) and the public
              train split (public seed in data/circuit_benchmark.py) from the
              ISCAS85 netlists, and compute the exact answer of every instance:
              the minimum diagnosis cardinality k* (MaxSAT, RC2) and the complete
              set of minimum-cardinality diagnoses (SAT enumeration under an
              at-most-k* cardinality constraint, blocking each solution).  The
              answer is checked independently: "at most k*-1" must be UNSAT and
              sampled diagnoses are re-validated by bit-parallel simulation.
              Instances whose answer cannot be enumerated within the offline
              budget are resampled (next attempt index of the same grid cell).
  calibrate   measure the evaluators' fixed calibration workload on this node.
  limit       choose the per-instance CPU budget from the reference method's
              behaviour on the PUBLIC train split only.
  baselines   run the HSD and BugAssist-vote baselines through both evaluators
              and store their raw outputs (evaluator-owned baseline results).

Test answers and the code/seed that regenerates them live only in eval/test.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from data.circuit_benchmark import (  # noqa: E402
    CIRCUITS,
    STRESS_CIRCUITS,
    TRAIN_SEED,
    cell_key,
    circuit_from_json,
    diagnosis_semantically_valid,
    grid,
    load_iscas85,
    make_instance,
    stress_grid,
    write_jsonl,
)

HIDDEN_SEED = "cfaults-hidden-test-bc3af558f0ea9b251fcb392af48fb5ab3ec2af68d8ce5da1"
BENCH_DIR = REPO_ROOT / "data" / "downloads" / "iscas85"
TEST_FILE = HERE / "hidden_benchmark.json"
TRAIN_DIR = REPO_ROOT / "data" / "iscas85_train"
TEST_CONFIG = HERE / "config.json"
TRAIN_CONFIG = REPO_ROOT / "eval" / "train" / "config.json"
MAX_DIAGNOSES = 3000
GT_CPU_BUDGET = {"base": 150.0, "stress": 120.0}
MAX_ATTEMPTS = {"base": 12, "stress": 2}
LIMIT_CANDIDATES = (2.5, 5.0, 10.0)
LIMIT_PROBE_CAP = 10.0
TARGET_MAX_TRAIN_COVERAGE = 75.0


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


def exact_answer(instance: dict, cpu_budget: float = 150.0) -> dict:
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
            if len(diagnoses) > MAX_DIAGNOSES:
                status = "too_many"
                break
            if time.process_time() - t0 > cpu_budget:
                status = "too_slow"
                break
            sat.add_clause([health[name] for name in diag])
    return {"optimum": k, "diagnoses": diagnoses, "status": status, "cpu_seconds": time.process_time() - t0}


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


def build_cells(split: str, seed_text: str, cells: list[tuple[str, str, int, int]]):
    circuits = {name: load_iscas85(BENCH_DIR, name) for name in CIRCUITS + STRESS_CIRCUITS}
    instances, truth, accepted, rejected, skipped = [], {}, {}, [], []
    rng = random.Random(f"verify|{seed_text}")
    for tier, circuit_name, k, m in cells:
        key = cell_key(tier, circuit_name, k, m)
        for attempt in range(MAX_ATTEMPTS[tier]):
            inst = make_instance(circuits[circuit_name], split, seed_text, k, m, attempt, tier)
            if inst is None:
                rejected.append({"cell": key, "attempt": attempt, "reason": "no_failing_observations"})
                continue
            answer = exact_answer(inst, GT_CPU_BUDGET[tier])
            if answer["status"] != "complete":
                rejected.append({"cell": key, "attempt": attempt, "reason": answer["status"],
                                 "optimum": answer["optimum"], "partial_count": len(answer["diagnoses"])})
                log(f"{split} {key} attempt {attempt}: rejected ({answer['status']})")
                continue
            verify_answer(inst, answer, rng)
            instances.append(inst)
            truth[inst["id"]] = {"optimum": answer["optimum"], "diagnoses": answer["diagnoses"],
                                 "enumeration_cpu_seconds": round(answer["cpu_seconds"], 3)}
            accepted[key] = attempt
            log(f"{split} {key} attempt {attempt}: k*={answer['optimum']} "
                f"#min={len(answer['diagnoses'])} ({answer['cpu_seconds']:.1f}s)")
            break
        else:
            if tier == "base":
                raise RuntimeError(f"no acceptable instance for {key}")
            skipped.append(key)
            log(f"{split} {key}: skipped (no attempt enumerable offline)")
    return instances, truth, accepted, rejected, skipped


def all_cells() -> list[tuple[str, str, int, int]]:
    return [("base", *c) for c in grid()] + [("stress", *c) for c in stress_grid()]


def phase_build() -> None:
    # hidden test split
    state = json.loads(TEST_FILE.read_text()) if TEST_FILE.exists() else {
        "instances": [], "ground_truth": {}, "accepted_attempts": {}, "rejected_attempts": []}
    state.setdefault("skipped_cells", [])
    for inst in state["instances"]:
        inst.setdefault("tier", "base")
    todo = [c for c in all_cells() if cell_key(*c) not in state["accepted_attempts"]
            and cell_key(*c) not in state["skipped_cells"]]
    for cell in todo:  # one cell at a time, saved after each (resumable)
        instances, truth, accepted, rejected, skipped = build_cells("test", HIDDEN_SEED, [cell])
        state["instances"] += instances
        state["ground_truth"].update(truth)
        state["accepted_attempts"].update(accepted)
        state["rejected_attempts"] += rejected
        state["skipped_cells"] += skipped
        TEST_FILE.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n")
    log(f"hidden test has {len(state['instances'])} instances")
    # public train split
    manifest_path = TRAIN_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        rows = [json.loads(line) for line in (TRAIN_DIR / "instances.jsonl").read_text().splitlines() if line.strip()]
        truth_all = json.loads((TRAIN_DIR / "ground_truth.json").read_text())
    else:
        manifest, rows, truth_all = {"accepted_attempts": {}, "rejected_attempts": []}, [], {}
    manifest.setdefault("skipped_cells", [])
    for row in rows:
        row.setdefault("tier", "base")
    todo = [c for c in all_cells() if cell_key(*c) not in manifest["accepted_attempts"]
            and cell_key(*c) not in manifest["skipped_cells"]]
    for cell in todo or [None]:
        if cell is not None:
            instances, truth, accepted, rejected, skipped = build_cells("train", TRAIN_SEED, [cell])
            rows += instances
            truth_all.update(truth)
            manifest["accepted_attempts"].update(accepted)
            manifest["rejected_attempts"] += rejected
            manifest["skipped_cells"] += skipped
        save_train(rows, truth_all, manifest, manifest_path)
    log(f"train split has {len(rows)} instances")


def save_train(rows, truth_all, manifest, manifest_path) -> None:
    write_jsonl(TRAIN_DIR / "instances.jsonl", rows)
    (TRAIN_DIR / "ground_truth.json").write_text(json.dumps(truth_all, sort_keys=True, separators=(",", ":")) + "\n")
    manifest.update({
        "name": "iscas85_multi_observation_diagnosis_train",
        "source": "ISCAS85 .bench netlists (scripts/download.sh), gate-type fault injection",
        "circuits": list(CIRCUITS), "stress_circuits": list(STRESS_CIRCUITS),
        "grid": [list(cell) for cell in grid()], "stress_grid": [list(cell) for cell in stress_grid()],
        "seed": TRAIN_SEED,
        "files": {"instances": "instances.jsonl", "ground_truth": "ground_truth.json"},
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def default_config(instances: list[dict]) -> dict:
    ids = sorted(inst["id"] for inst in instances if inst["source_circuit"] == "c880" and inst["observation_count"] == 50)
    return {"cpu_limit_seconds": 10.0, "required_methods": ["cfaults"],
            "calibration": {"instance_ids": ids, "reference_cpu_seconds": None}}


def load_split(split: str) -> list[dict]:
    if split == "test":
        return json.loads(TEST_FILE.read_text())["instances"]
    return [json.loads(line) for line in (TRAIN_DIR / "instances.jsonl").read_text().splitlines() if line.strip()]


def ensure_configs() -> None:
    for split, path in (("test", TEST_CONFIG), ("train", TRAIN_CONFIG)):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(default_config(load_split(split)), indent=2, sort_keys=True) + "\n")


def evaluator(split: str) -> str:
    return f"eval/{split}/evaluate_circuit_outputs.py"


def phase_calibrate() -> None:
    ensure_configs()
    for split, path in (("test", TEST_CONFIG), ("train", TRAIN_CONFIG)):
        cfg = json.loads(path.read_text())
        if cfg["calibration"].get("reference_cpu_seconds"):
            continue
        out = subprocess.run([sys.executable, "-I", evaluator(split), "--calibrate-only"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True)
        value = json.loads(out.stdout.strip().splitlines()[-1])["cpu_seconds"]
        cfg["calibration"]["reference_cpu_seconds"] = value
        path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
        log(f"{split} calibration workload: {value:.3f} cpu-s")


def phase_limit() -> None:
    cfg = json.loads(TRAIN_CONFIG.read_text())
    if cfg.get("limit_selection"):
        return
    reg = REPO_ROOT / "checkpoints" / "cfaults_circuit" / "solver.json"
    if not reg.exists():
        subprocess.run([sys.executable, "method/cfaults_circuit.py", "--register"], cwd=REPO_ROOT, check=True)
    probe_out = REPO_ROOT / "tmp" / "limit_probe_scores.json"
    subprocess.run([sys.executable, "-I", evaluator("train"), "--cpu-limit", str(LIMIT_PROBE_CAP), "--methods", "cfaults",
                    "--out", str(probe_out)], cwd=REPO_ROOT, check=True)
    records = json.loads((REPO_ROOT / "eval" / "train" / "runs" / "cfaults.json").read_text())["records"]
    truth = json.loads((TRAIN_DIR / "ground_truth.json").read_text())
    coverage = {}
    per_instance = []
    for rec in records:
        expected = {frozenset(d) for d in truth[rec["id"]]["diagnoses"]}
        got = {frozenset(d) for d in rec["diagnoses"] if isinstance(d, list)}
        complete = got == expected and len(rec["diagnoses"]) == len(expected)
        per_instance.append({"id": rec["id"], "complete": complete, "status": rec["status"], "cpu": rec["cpu_seconds"]})
    for cand in LIMIT_CANDIDATES:
        ok = sum(1 for r in per_instance if r["complete"] and r["status"] == "ok" and r["cpu"] <= cand)
        coverage[str(cand)] = 100.0 * ok / max(1, len(per_instance))
    eligible = [c for c in LIMIT_CANDIDATES if coverage[str(c)] <= TARGET_MAX_TRAIN_COVERAGE]
    chosen = max(eligible) if eligible else min(LIMIT_CANDIDATES)
    selection = {"rule": f"largest candidate budget at which the reference localises <= {TARGET_MAX_TRAIN_COVERAGE}% "
                         "of the public TRAIN instances (keeps headroom); smallest candidate if none",
                 "candidates": list(LIMIT_CANDIDATES), "train_reference_coverage": coverage, "chosen": chosen,
                 "probe_cap_seconds": LIMIT_PROBE_CAP}
    for path in (TRAIN_CONFIG, TEST_CONFIG):
        c = json.loads(path.read_text())
        c["cpu_limit_seconds"] = chosen
        c["limit_selection"] = selection
        path.write_text(json.dumps(c, indent=2, sort_keys=True) + "\n")
    (REPO_ROOT / "tmp" / "limit_probe_per_instance.json").write_text(json.dumps(per_instance, indent=2) + "\n")
    log(f"chosen cpu limit {chosen}s; train coverage by candidate {coverage}")


BASELINES = {
    "hsd": ["python", "baseline/hsd_circuit.py", "--instance", "{instance}", "--output", "{output}"],
    "bugassist_vote": ["python", "baseline/bugassist_vote_circuit.py", "--instance", "{instance}", "--output", "{output}"],
}


def phase_baselines() -> None:
    for split in ("test", "train"):
        for name, command in BASELINES.items():
            target = REPO_ROOT / "eval" / split / "baseline_outputs" / f"{name}.json"
            if target.exists():
                continue
            log(f"running baseline {name} on {split}")
            subprocess.run([sys.executable, "-I", evaluator(split), "--store-baseline", name,
                            "--command-json", json.dumps(command)], cwd=REPO_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", choices=["build", "calibrate", "limit", "baselines", "all"])
    args = parser.parse_args()
    os.chdir(REPO_ROOT)
    phases = ["build", "calibrate", "limit", "baselines"] if args.phase == "all" else [args.phase]
    for phase in phases:
        log(f"phase {phase}")
        {"build": phase_build, "calibrate": phase_calibrate, "limit": phase_limit, "baselines": phase_baselines}[phase]()


if __name__ == "__main__":
    main()
