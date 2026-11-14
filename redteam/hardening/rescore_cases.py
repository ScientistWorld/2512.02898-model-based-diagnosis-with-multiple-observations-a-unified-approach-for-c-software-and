#!/usr/bin/env python3
"""Rescore saved audit runs at the configured budget, without running any method.

Every run records, for each diagnosis, the counted work at which it was
observed in the output file, and counts are exact, so scoring a run made
with a larger cap at a smaller budget gives exactly what a run at that
budget gives.  Used when the budget changed after the audit job (hardening 12:
60G -> 30G instructions).
"""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "redteam" / "hardening" / "results"


def main() -> None:
    spec = importlib.util.spec_from_file_location("test_eval", ROOT / "eval/test/evaluate_circuit_outputs.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    config = json.loads((ROOT / "eval" / "test" / "config.json").read_text())
    budget = float(config["instruction_budget"])
    fractions = {k: float(v) for k, v in config["budget_fractions"].items()}
    instances, truth = ev.load_benchmark()
    for case_dir in sorted(p for p in RESULTS.iterdir() if p.is_dir() and p.name != "reference"):
        runs = sorted((case_dir / "runs").glob("*.json.gz"))
        old = json.loads((case_dir / "scores_test.json").read_text()) if (case_dir / "scores_test.json").exists() else {}
        per_method = {}
        for path in runs:
            with gzip.open(path, "rt") as fh:
                payload = json.load(fh)
            cap = float(payload.get("run", {}).get("cap", budget))
            per_method[path.name[: -len(".json.gz")]] = ev.aggregate(payload.get("records", []), instances, truth,
                                                                     min(budget, cap), fractions)
        if not per_method:
            print(f"{case_dir.name}: no saved runs, kept")
            continue
        extra = {"_evaluation": {**old.get("_evaluation", {}), "rescored": {
            "instruction_budget": budget, "budget_fractions": fractions,
            "note": "rescored from the saved raw outputs of the audit job (run with a 60G cap)"}}}
        extra["_evaluation"].setdefault("budget", {})["instruction_budget"] = budget
        ev.write_scores(per_method, case_dir / "scores_test.json", extra)
        print(f"{case_dir.name}: rescored {sorted(per_method)}")


if __name__ == "__main__":
    main()
