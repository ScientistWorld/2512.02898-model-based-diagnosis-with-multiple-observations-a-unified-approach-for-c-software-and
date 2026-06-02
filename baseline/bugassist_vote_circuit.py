#!/usr/bin/env python3
"""BugAssist-style per-observation diagnosis voting baseline for circuits."""

from __future__ import annotations

import argparse
import collections
import itertools
import json
import time
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from data.circuit_benchmark import circuit_from_json  # noqa: E402


Clause = list[int]


class VarPool:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}

    def id(self, name: str) -> int:
        if name not in self._ids:
            self._ids[name] = len(self._ids) + 1
        return self._ids[name]

    @property
    def top(self) -> int:
        return len(self._ids)


def guarded_equiv_clauses(op: str, out: int, ins: list[int], guard: int) -> list[Clause]:
    gneg = -guard
    if op == "BUF":
        return [[gneg, -out, ins[0]], [gneg, out, -ins[0]]]
    if op == "NOT":
        return [[gneg, -out, -ins[0]], [gneg, out, ins[0]]]
    if op == "AND":
        return [[gneg, out, *[-x for x in ins]], *[[gneg, -out, x] for x in ins]]
    if op == "NAND":
        return [[gneg, -out, *[-x for x in ins]], *[[gneg, out, x] for x in ins]]
    if op == "OR":
        return [[gneg, -out, *ins], *[[gneg, out, -x] for x in ins]]
    if op == "NOR":
        return [[gneg, out, *ins], *[[gneg, -out, -x] for x in ins]]
    if op == "XOR":
        a, b = ins
        return [
            [gneg, -a, -b, -out],
            [gneg, -a, b, out],
            [gneg, a, -b, out],
            [gneg, a, b, -out],
        ]
    raise ValueError(f"unsupported op {op}")


def build_one_observation_formula(circuit, observation: dict) -> tuple[list[Clause], list[int], int, dict[int, str]]:
    pool = VarPool()
    healthy = {gate.name: pool.id(f"h::{gate.name}") for gate in circuit.gates}
    hard: list[Clause] = []

    def v(name: str) -> int:
        return pool.id(f"o0::{name}")

    for name, value in observation["inputs"].items():
        hard.append([v(name) if value else -v(name)])
    for gate in circuit.gates:
        hard.extend(guarded_equiv_clauses(gate.op, v(gate.name), [v(name) for name in gate.inputs], healthy[gate.name]))
    for name, value in observation["expected_outputs"].items():
        hard.append([v(name) if value else -v(name)])
    return hard, list(healthy.values()), pool.top, {lit: name for name, lit in healthy.items()}


def clause_sat(clause: Clause, assignment: dict[int, bool]) -> bool:
    return any(assignment.get(abs(lit), False) == (lit > 0) for lit in clause)


def solve_one_observation(
    hard: list[Clause],
    soft: list[int],
    top: int,
    block: list[Clause] | None,
    solver: str,
) -> tuple[set[int] | None, int | None, str]:
    if solver in {"auto", "pysat"}:
        try:
            from pysat.examples.rc2 import RC2Stratified
            from pysat.formula import WCNF

            wcnf = WCNF()
            for clause in hard:
                wcnf.append(clause)
            for clause in block or []:
                wcnf.append(clause)
            for lit in soft:
                wcnf.append([lit], weight=1)
            wcnf.nv = max(top, wcnf.nv)
            with RC2Stratified(wcnf) as rc2:
                model = rc2.compute()
                if model is None:
                    return None, None, "pysat_rc2stratified"
                assigned = set(model)
                disabled = {lit for lit in soft if -lit in assigned}
                return disabled, len(disabled), "pysat_rc2stratified"
        except ModuleNotFoundError:
            if solver == "pysat":
                raise

    clauses = hard + (block or [])
    best: set[int] | None = None
    for bits in itertools.product([False, True], repeat=top):
        assignment = {idx + 1: bits[idx] for idx in range(top)}
        if not all(clause_sat(clause, assignment) for clause in clauses):
            continue
        disabled = {lit for lit in soft if not assignment[lit]}
        if best is None or len(disabled) < len(best):
            best = disabled
    return (best, len(best), "exhaustive") if best is not None else (None, None, "exhaustive")


def diagnose_one_observation(circuit, observation: dict, solver: str) -> dict:
    start = time.perf_counter()
    hard, soft, top, names = build_one_observation_formula(circuit, observation)
    block: list[Clause] = []
    diagnoses: list[list[str]] = []
    optimum = None
    solver_used = "unknown"
    while True:
        disabled, cost, solver_used = solve_one_observation(hard, soft, top, block, solver)
        if disabled is None or cost is None:
            break
        if optimum is None:
            optimum = cost
        if cost > optimum:
            break
        diag = sorted(names[lit] for lit in disabled)
        if diag not in diagnoses:
            diagnoses.append(diag)
        if not disabled:
            break
        block.append([lit for lit in disabled])
    return {
        "diagnoses": diagnoses,
        "diagnosis_count": len(diagnoses),
        "optimum_cost": optimum,
        "elapsed_sec": time.perf_counter() - start,
        "solver": solver_used,
    }


def run_baseline(benchmark: Path, out: Path, limit: int = 0, solver: str = "auto") -> None:
    manifest = json.loads((benchmark / "manifest.json").read_text())
    results = {"method": "bugassist_vote", "benchmark": manifest["name"], "instances": []}
    for entry in manifest["instances"][: limit or None]:
        instance = json.loads((benchmark / entry["path"]).read_text())
        circuit = circuit_from_json(instance["faulty_circuit"])
        votes: collections.Counter[tuple[str, ...]] = collections.Counter()
        per_obs = []
        for obs in instance["observations"]:
            result = diagnose_one_observation(circuit, obs, solver=solver)
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
