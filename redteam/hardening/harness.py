#!/usr/bin/env python3
"""Run audit cases through the real hidden test (``bash scripts/evaluate_test.sh``).

Each case gets a fresh copy of the workspace (data, method, baseline, scripts,
eval incl. the hidden test as restored for scoring), its own method
registrations under ``checkpoints/``, optional pre-steps (e.g. pre-written
scores), and then the hidden test is run with no arguments.  Scores and raw
per-instance records are kept in ``redteam/hardening/results/<case>/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARD = ROOT / "redteam" / "hardening"
RESULTS = HARD / "results"
WORK = HARD / "workspaces"
# Cases named "<case>__before" are scored by the hidden-test evaluator as it was
# before this hardening iteration (process-tree CPU accounting and tamper
# detection absent), to measure what the fixed shortcuts paid.
BEFORE_EVALUATOR = HARD / "before" / "evaluate_test_before.py"


def force_rmtree(path: Path) -> None:
    """rmtree that also handles directories left at mode 0 by an interrupted hidden test."""
    if not path.exists():
        return
    for root, dirs, _ in os.walk(path):
        for d in dirs:
            try:
                os.chmod(os.path.join(root, d), 0o700)
            except OSError:
                pass
    # os.walk cannot list a mode-0 directory before it is chmod-ed: repeat until clean
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

# name -> (registrations {checkpoint_dir: command}, env overrides, pre-step)
CASES = {
    "lazy_observations": ({"cfaults_circuit": var("lazy_observations")}, {}, None),
    "fresh_solver_previous_reference": ({"cfaults_circuit": var("fresh_solver")}, {}, None),
    "satenum": ({"cfaults_circuit": var("satenum")}, {}, None),
    "hsd_as_method": ({"cfaults_circuit": HSD}, {}, None),
    "weaker_one_observation": ({"cfaults_circuit": var("weaker_one_observation")}, {}, None),
    "first_only": ({"cfaults_circuit": var("first_only")}, {}, None),
    "hidden_file_read_shortcut": ({"cfaults_circuit": cut("hidden_file_read")}, {}, None),
    "golden_diff_shortcut": ({"cfaults_circuit": cut("golden_diff")}, {}, None),
    "train_answer_lookup_shortcut": ({"cfaults_circuit": cut("train_answer_lookup")}, {}, None),
    "all_gates_shortcut": ({"cfaults_circuit": cut("all_gates")}, {}, None),
    "constant_gate_shortcut": ({"cfaults_circuit": cut("constant_gate")}, {}, None),
    "claimed_success_shortcut": ({"cfaults_circuit": cut("claimed_success")}, {}, None),
    "singleton_spam_shortcut": ({"cfaults_circuit": cut("singleton_spam")}, {}, None),
    "empty_output_shortcut": ({"cfaults_circuit": cut("empty_output")}, {}, None),
    "crash_shortcut": ({"cfaults_circuit": cut("crash")}, {}, None),
    "unregistered_shortcut": ({}, {}, None),
    "late_method_shortcut": ({"cfaults_circuit": cut("constant_gate"), "late_method": cut("empty_output")}, {}, "late"),
    "replace_baseline_shortcut": ({"cfaults_circuit": cut("constant_gate"), "hsd_circuit": cut("empty_output"),
                                   "bugassist_vote": cut("empty_output")}, {}, None),
    "prewrite_scores_shortcut": ({"cfaults_circuit": cut("constant_gate")}, {}, "prewrite"),
    "brute_force": ({"cfaults_circuit": var("brute_force")}, {}, None),
    "nonminimal_padding_shortcut": ({"cfaults_circuit": cut("nonminimal_padding")}, {}, None),
    "duplicate_diagnosis_shortcut": ({"cfaults_circuit": cut("duplicate_diagnosis")}, {}, None),
    "reference_seed_1": ({"cfaults_circuit": ref()}, {"PYTHONHASHSEED": "1"}, None),
    "reference_seed_2": ({"cfaults_circuit": ref()}, {"PYTHONHASHSEED": "2"}, None),
    # Shortcuts closed in hardening iteration 11 (part 2), each also run against the previous evaluator.
    "chmod_hidden_read_shortcut": ({"cfaults_circuit": cut("chmod_hidden_read")}, {}, None),
    "chmod_hidden_read_shortcut__before": ({"cfaults_circuit": cut("chmod_hidden_read")}, {}, None),
    "cpu_escape_relay_shortcut": ({"cfaults_circuit": cut("cpu_escape_relay")}, {}, None),
    "cpu_escape_relay_shortcut__before": ({"cfaults_circuit": cut("cpu_escape_relay")}, {}, None),
}


def stage(case: str, registrations: dict, pre: str | None) -> Path:
    work = WORK / case
    force_rmtree(work)
    work.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "runs", "*.pyc")
    for name in ("data", "method", "baseline", "scripts", "eval"):
        shutil.copytree(ROOT / name, work / name, ignore=ignore)
    (work / "scoring").mkdir()
    for doc in ("TARGETS.md", "CONSTRAINTS.md", "DIRECTION.md", "EXPERIMENTS.md", "scores_train.json"):
        if (ROOT / "scoring" / doc).exists():
            shutil.copy2(ROOT / "scoring" / doc, work / "scoring" / doc)
    shutil.copy2(HARD / "audit_variants.py", work / "method" / "audit_variants.py")
    shutil.copy2(HARD / "audit_shortcuts.py", work / "method" / "audit_shortcuts.py")
    if case.endswith("__before"):
        shutil.copy2(BEFORE_EVALUATOR, work / "eval" / "test" / "evaluate_circuit_outputs.py")
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
        path.write_text(json.dumps({"command": registrations["late_method"]}) + "\n")
    return work


def execute(case: str) -> None:
    out = RESULTS / case
    if (out / "scores_test.json").exists():
        print(f"skip {case} (done)", flush=True)
        return
    registrations, env_over, pre = CASES[case]
    work = stage(case, registrations, pre)
    env = dict(os.environ, **env_over)
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()
    with (out / "run.log").open("w") as log:
        proc = subprocess.run(["bash", "scripts/evaluate_test.sh"], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
    meta = {"case": case, "hidden_command": ["bash", "scripts/evaluate_test.sh"], "hidden_arguments": [],
            "returncode": proc.returncode, "wall_seconds": time.time() - start,
            "registrations": registrations, "env": env_over, "pre_step": pre}
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
    cases = sys.argv[1:] or list(CASES)
    if cases == ["all"]:
        cases = list(CASES)
    failures = {}
    for case in cases:
        try:
            execute(case)
        except Exception as exc:  # keep going; record the failure
            failures[case] = repr(exc)
            print(f"FAILED {case}: {exc!r}", flush=True)
    if failures:
        (RESULTS / "harness_failures.json").write_text(json.dumps(failures, indent=2) + "\n")


if __name__ == "__main__":
    main()
