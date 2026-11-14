#!/usr/bin/env python3
"""Run audit cases through the real hidden test (``bash scripts/evaluate_test.sh``).

``snapshot`` copies the gym as the hidden test will see it (data, method,
baseline, scripts, eval incl. the hidden test) into ``redteam/hardening/snapshot``
once the benchmark and budget are fixed.  Each case then gets a fresh copy of
that snapshot, its own method registrations under ``checkpoints/``, optional
pre-steps (e.g. pre-written scores), and the hidden test is run with no
arguments.  Cases run in parallel (instruction counts do not depend on load).
Scores and raw per-instance records are kept in ``redteam/hardening/results/<case>/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "redteam" / "hardening"
RESULTS = HARD / "results"
WORK = HARD / "workspaces"
SNAPSHOT = HARD / "snapshot"


def force_rmtree(path: Path) -> None:
    """rmtree that also handles directories left at mode 0 by an interrupted hidden test."""
    if not path.exists():
        return
    for _ in range(10):
        stuck = []
        for root, dirs, _ in os.walk(path):
            for d in dirs:
                full = os.path.join(root, d)
                if not os.access(full, os.R_OK | os.X_OK):
                    stuck.append(full)
        if not stuck:
            break
        for d in stuck:
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
    shutil.rmtree(path, ignore_errors=True)


def ref():
    return ["python", "method/cfaults_circuit.py", "--instance", "{instance}", "--output", "{output}"]


def var(name):
    return ["python", "method/audit_variants.py", name, "--instance", "{instance}", "--output", "{output}"]


def cut(name):
    return ["python", "method/audit_shortcuts.py", name, "--instance", "{instance}", "--output", "{output}"]


HSD = ["python", "baseline/hsd_circuit.py", "--instance", "{instance}", "--output", "{output}"]
VOTE = ["python", "baseline/bugassist_vote_circuit.py", "--instance", "{instance}", "--output", "{output}"]

# name -> (registrations {checkpoint_dir: command}, pre-step); heavy cases first
CASES = {
    "brute_force": ({"cfaults_circuit": var("brute_force")}, None),
    "parallel_portfolio_shortcut": ({"cfaults_circuit": cut("parallel_portfolio")}, None),
    "reference_repeat": ({"cfaults_circuit": ref()}, None),
    "exhaust_minz": ({"cfaults_circuit": var("exhaust_minz")}, None),
    "fresh_solver_previous_reference": ({"cfaults_circuit": var("fresh_solver")}, None),
    "lazy_observations": ({"cfaults_circuit": var("lazy_observations")}, None),
    "lean": ({"cfaults_circuit": var("lean")}, None),
    "lean_exhaust_minz": ({"cfaults_circuit": var("lean_exhaust_minz")}, None),
    "hsd_as_method": ({"cfaults_circuit": HSD}, None),
    "bugassist_vote_as_method": ({"cfaults_circuit": VOTE}, None),
    "cpu_escape_relay_shortcut": ({"cfaults_circuit": cut("cpu_escape_relay")}, None),
    "perf_disable_shortcut": ({"cfaults_circuit": cut("perf_disable")}, None),
    "placeholder_overwrite_shortcut": ({"cfaults_circuit": cut("placeholder_overwrite")}, None),
    "nonminimal_padding_shortcut": ({"cfaults_circuit": cut("nonminimal_padding")}, None),
    "duplicate_diagnosis_shortcut": ({"cfaults_circuit": cut("duplicate_diagnosis")}, None),
    "first_only": ({"cfaults_circuit": var("first_only")}, None),
    "weaker_one_observation": ({"cfaults_circuit": var("weaker_one_observation")}, None),
    "chmod_hidden_read_shortcut": ({"cfaults_circuit": cut("chmod_hidden_read")}, None),
    "hidden_file_read_shortcut": ({"cfaults_circuit": cut("hidden_file_read")}, None),
    "golden_diff_shortcut": ({"cfaults_circuit": cut("golden_diff")}, None),
    "train_answer_lookup_shortcut": ({"cfaults_circuit": cut("train_answer_lookup")}, None),
    "all_gates_shortcut": ({"cfaults_circuit": cut("all_gates")}, None),
    "constant_gate_shortcut": ({"cfaults_circuit": cut("constant_gate")}, None),
    "claimed_success_shortcut": ({"cfaults_circuit": cut("claimed_success")}, None),
    "singleton_spam_shortcut": ({"cfaults_circuit": cut("singleton_spam")}, None),
    "empty_output_shortcut": ({"cfaults_circuit": cut("empty_output")}, None),
    "crash_shortcut": ({"cfaults_circuit": cut("crash")}, None),
    "unregistered_shortcut": ({}, None),
    "late_method_shortcut": ({"cfaults_circuit": cut("constant_gate"), "late_method": cut("empty_output")}, "late"),
    "replace_baseline_shortcut": ({"cfaults_circuit": cut("constant_gate"), "hsd_circuit": cut("empty_output"),
                                   "bugassist_vote": cut("empty_output")}, None),
    "prewrite_scores_shortcut": ({"cfaults_circuit": cut("constant_gate")}, "prewrite"),
}


def snapshot() -> None:
    force_rmtree(SNAPSHOT)
    SNAPSHOT.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "runs", "*.pyc", "baseline_outputs", "downloads")
    for name in ("data", "method", "baseline", "scripts", "eval"):
        shutil.copytree(ROOT / name, SNAPSHOT / name, ignore=ignore)
    shutil.copytree(ROOT / "data" / "downloads", SNAPSHOT / "data" / "downloads")
    print(f"snapshot at {SNAPSHOT}", flush=True)


def stage(case: str, registrations: dict, pre: str | None) -> Path:
    work = WORK / case
    force_rmtree(work)
    shutil.copytree(SNAPSHOT, work)
    (work / "scoring").mkdir()
    for doc in ("TARGETS.md", "CONSTRAINTS.md", "DIRECTION.md", "EXPERIMENTS.md"):
        if (ROOT / "scoring" / doc).exists():
            shutil.copy2(ROOT / "scoring" / doc, work / "scoring" / doc)
    shutil.copy2(HARD / "audit_variants.py", work / "method" / "audit_variants.py")
    shutil.copy2(HARD / "audit_shortcuts.py", work / "method" / "audit_shortcuts.py")
    (work / "checkpoints").mkdir()
    for directory, command in registrations.items():
        if pre == "late" and directory == "late_method":
            continue
        path = work / "checkpoints" / directory / "solver.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"command": command}) + "\n")
    if pre == "prewrite":
        fake = {"experiments": {"iscas85_localisation": {"results": {"cfaults": {"localized_rate": 1e99}}}}, "marker": "prewritten"}
        (work / "scoring" / "scores_test.json").write_text(json.dumps(fake))
    if pre == "late":
        # public train evaluation happens first (scientist workflow), then a method appears on disk
        subprocess.run(["bash", "scripts/evaluate_train.sh"], cwd=work, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        path = work / "checkpoints" / "late_method" / "solver.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"command": CASES[case][0]["late_method"]}) + "\n")
    return work


def execute(case: str) -> None:
    out = RESULTS / case
    if (out / "scores_test.json").exists():
        print(f"skip {case} (done)", flush=True)
        return
    registrations, pre = CASES[case]
    work = stage(case, registrations, pre)
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()
    with (out / "run.log").open("w") as log:
        proc = subprocess.run(["bash", "scripts/evaluate_test.sh"], cwd=work, stdout=log, stderr=subprocess.STDOUT)
    meta = {"case": case, "hidden_command": ["bash", "scripts/evaluate_test.sh"], "hidden_arguments": [],
            "returncode": proc.returncode, "wall_seconds": time.time() - start,
            "registrations": registrations, "pre_step": pre}
    scores = work / "scoring" / "scores_test.json"
    if scores.exists():
        shutil.copy2(scores, out / "scores_test.json.tmp")
    runs = work / "eval" / "test" / "runs"
    if runs.exists():
        shutil.copytree(runs, out / "runs", dirs_exist_ok=True)
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    if (out / "scores_test.json.tmp").exists():
        (out / "scores_test.json.tmp").rename(out / "scores_test.json")
    force_rmtree(work)
    print(f"finished {case} rc={proc.returncode} in {meta['wall_seconds']:.0f}s", flush=True)


def main() -> None:
    args = sys.argv[1:]
    if args == ["snapshot"]:
        snapshot()
        return
    jobs = 1
    if args and args[0].startswith("--jobs="):
        jobs = max(1, int(args[0].split("=", 1)[1]))
        args = args[1:]
    cases = list(CASES) if not args or args == ["all"] else args
    failures = {}

    def guarded(case: str) -> None:
        try:
            execute(case)
        except Exception as exc:  # keep going; record the failure
            failures[case] = repr(exc)
            print(f"FAILED {case}: {exc!r}", flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        list(pool.map(guarded, cases))
    if failures:
        RESULTS.mkdir(parents=True, exist_ok=True)
        (RESULTS / "harness_failures.json").write_text(json.dumps(failures, indent=2) + "\n")


if __name__ == "__main__":
    main()
