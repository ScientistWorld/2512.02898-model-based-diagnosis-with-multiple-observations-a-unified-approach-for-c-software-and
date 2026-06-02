#!/usr/bin/env python3
"""BugAssist-style per-observation diagnosis voting baseline for circuits."""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from data.circuit_benchmark import circuit_from_json  # noqa: E402
from method.cfaults_circuit import diagnose  # noqa: E402


def run_baseline(benchmark: Path, out: Path, limit: int = 0, solver: str = "auto") -> None:
    manifest = json.loads((benchmark / "manifest.json").read_text())
    results = {"method": "bugassist_vote", "benchmark": manifest["name"], "instances": []}
    for entry in manifest["instances"][: limit or None]:
        instance = json.loads((benchmark / entry["path"]).read_text())
        circuit = circuit_from_json(instance["faulty_circuit"])
        votes: collections.Counter[tuple[str, ...]] = collections.Counter()
        per_obs = []
        for obs in instance["observations"]:
            result = diagnose(circuit, [obs], enumerate_all=True, solver=solver)
            for diag in result["diagnoses"]:
                votes[tuple(diag)] += 1
            per_obs.append(result)
        ranked = sorted(votes, key=lambda item: (-votes[item], len(item), item))
        chosen = list(ranked[0]) if ranked else []
        results["instances"].append(
            {
                "id": instance["id"],
                "path": entry["path"],
                "fault_count": instance["fault_count"],
                "observation_count": instance["observation_count"],
                "true_faults": sorted(instance["faults"]),
                "diagnoses": [chosen],
                "diagnosis_count": len(votes),
                "optimum_cost": len(chosen),
                "per_observation_diagnosis_total": sum(r["diagnosis_count"] for r in per_obs),
                "elapsed_sec": sum(r["elapsed_sec"] for r in per_obs),
                "solver": per_obs[0]["solver"] if per_obs else "none",
            }
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=Path("data/synthetic_circuits"))
    parser.add_argument("--out", type=Path, default=Path("checkpoints/bugassist_vote/results.json"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--solver", choices=["auto", "pysat", "exhaustive"], default="auto")
    args = parser.parse_args()
    run_baseline(args.benchmark, args.out, args.limit, args.solver)


if __name__ == "__main__":
    main()
