#!/usr/bin/env python3
"""CFaults-style unified MaxSAT diagnosis for Boolean circuits."""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from data.circuit_benchmark import Circuit, circuit_from_json  # noqa: E402


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
    """Return CNF clauses for guard -> (out <-> op(ins))."""
    gneg = -guard
    if op == "BUF":
        return [[gneg, -out, ins[0]], [gneg, out, -ins[0]]]
    if op == "NOT":
        return [[gneg, -out, -ins[0]], [gneg, out, ins[0]]]
    if op == "AND":
        return [[gneg, -out, *ins], *[[gneg, out, -x] for x in ins]]
    if op == "NAND":
        return [[gneg, out, *ins], *[[gneg, -out, -x] for x in ins]]
    if op == "OR":
        return [[gneg, out, *[-x for x in ins]], *[[gneg, -out, x] for x in ins]]
    if op == "NOR":
        return [[gneg, -out, *[-x for x in ins]], *[[gneg, out, x] for x in ins]]
    if op == "XOR":
        if len(ins) != 2:
            raise ValueError("XOR encoder expects two inputs")
        a, b = ins
        return [
            [gneg, -a, -b, -out],
            [gneg, -a, b, out],
            [gneg, a, -b, out],
            [gneg, a, b, -out],
        ]
    raise ValueError(f"unsupported op {op}")


def build_unified_formula(circuit: Circuit, observations: list[dict]) -> tuple[list[Clause], list[int], VarPool, dict[str, int]]:
    pool = VarPool()
    healthy = {gate.name: pool.id(f"h::{gate.name}") for gate in circuit.gates}
    hard: list[Clause] = []
    for obs_idx, obs in enumerate(observations):
        def v(name: str) -> int:
            return pool.id(f"o{obs_idx}::{name}")

        for name, value in obs["inputs"].items():
            hard.append([v(name) if value else -v(name)])
        for gate in circuit.gates:
            out = v(gate.name)
            ins = [v(name) for name in gate.inputs]
            hard.extend(guarded_equiv_clauses(gate.op, out, ins, healthy[gate.name]))
        for name, value in obs["expected_outputs"].items():
            hard.append([v(name) if value else -v(name)])
    return hard, list(healthy.values()), pool, healthy


def solve_with_pysat(hard: list[Clause], soft: list[int], top: int, block: list[Clause] | None = None) -> tuple[set[int] | None, int | None]:
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
    with RC2Stratified(wcnf) as solver:
        model = solver.compute()
        if model is None:
            return None, None
        assigned = set(model)
        disabled = {lit for lit in soft if -lit in assigned}
        return disabled, len(disabled)


def clause_sat(clause: Clause, assignment: dict[int, bool]) -> bool:
    for lit in clause:
        val = assignment.get(abs(lit))
        if val is not None and val == (lit > 0):
            return True
    return False


def solve_with_exhaustive(hard: list[Clause], soft: list[int], top: int, block: list[Clause] | None = None) -> tuple[set[int] | None, int | None]:
    """Tiny fallback for smoke tests when PySAT is not installed."""
    clauses = hard + (block or [])
    best: set[int] | None = None
    for bits in itertools.product([False, True], repeat=top):
        assignment = {idx + 1: bits[idx] for idx in range(top)}
        if not all(clause_sat(clause, assignment) for clause in clauses):
            continue
        disabled = {lit for lit in soft if not assignment[lit]}
        if best is None or len(disabled) < len(best):
            best = disabled
    return (best, len(best)) if best is not None else (None, None)


def solve_formula(hard: list[Clause], soft: list[int], top: int, block: list[Clause] | None = None, solver: str = "auto") -> tuple[set[int] | None, int | None, str]:
    if solver in {"auto", "pysat"}:
        try:
            disabled, cost = solve_with_pysat(hard, soft, top, block)
            return disabled, cost, "pysat_rc2stratified"
        except ModuleNotFoundError:
            if solver == "pysat":
                raise
    disabled, cost = solve_with_exhaustive(hard, soft, top, block)
    return disabled, cost, "exhaustive"


def diagnose(
    circuit: Circuit,
    observations: list[dict],
    enumerate_all: bool = True,
    solver: str = "auto",
) -> dict:
    start = time.perf_counter()
    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    inv_healthy = {lit: name for name, lit in healthy.items()}
    solutions: list[list[str]] = []
    optimum = None
    block: list[Clause] = []
    solver_used = "unknown"
    while True:
        disabled, cost, solver_used = solve_formula(hard, soft, pool.top, block, solver)
        if disabled is None or cost is None:
            break
        if optimum is None:
            optimum = cost
        if cost > optimum:
            break
        diag = sorted(inv_healthy[lit] for lit in disabled)
        if diag not in solutions:
            solutions.append(diag)
        if not enumerate_all:
            break
        if not disabled:
            break
        block.append([lit for lit in disabled])
    elapsed = time.perf_counter() - start
    return {
        "solver": solver_used,
        "diagnoses": solutions,
        "diagnosis_count": len(solutions),
        "optimum_cost": optimum,
        "num_observations": len(observations),
        "num_gates": len(circuit.gates),
        "num_hard_clauses": len(hard),
        "num_soft_clauses": len(soft),
        "elapsed_sec": elapsed,
    }


def load_instance(benchmark_dir: Path, instance_path: str) -> tuple[Circuit, dict]:
    manifest = json.loads((benchmark_dir / "manifest.json").read_text())
    instance = json.loads((benchmark_dir / instance_path).read_text())
    if "faulty_circuit" in instance:
        circuit = circuit_from_json(instance["faulty_circuit"])
    else:
        circuit = circuit_from_json(json.loads((benchmark_dir / manifest["circuit"]).read_text()))
    return circuit, instance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=Path("data/synthetic_circuits"))
    parser.add_argument("--out", type=Path, default=Path("checkpoints/cfaults_circuit/results.json"))
    parser.add_argument("--limit", type=int, default=0, help="0 means all instances")
    parser.add_argument("--solver", choices=["auto", "pysat", "exhaustive"], default="auto")
    parser.add_argument("--first-only", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.benchmark / "manifest.json").read_text())
    selected = manifest["instances"][: args.limit or None]
    results = {"method": "cfaults_unified_maxsat", "benchmark": manifest["name"], "instances": []}
    for entry in selected:
        circuit, instance = load_instance(args.benchmark, entry["path"])
        result = diagnose(
            circuit,
            instance["observations"],
            enumerate_all=not args.first_only,
            solver=args.solver,
        )
        result.update(
            {
                "id": instance["id"],
                "path": entry["path"],
                "fault_count": instance["fault_count"],
                "observation_count": instance["observation_count"],
                "true_faults": sorted(instance["faults"]),
            }
        )
        results["instances"].append(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
