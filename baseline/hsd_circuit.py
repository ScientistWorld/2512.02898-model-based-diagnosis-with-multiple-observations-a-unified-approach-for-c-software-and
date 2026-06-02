#!/usr/bin/env python3
"""HSD-style multi-observation circuit diagnosis baseline.

This implements the hitting-set dualisation baseline described in the paper's
Algorithm 4 for the scaled Boolean-circuit benchmark.  Each failing observation
is encoded as a separate circuit replica, the original gate health variables
are shared across replicas, and minimum hitting sets of unsat cores are tested
until minimum-cardinality aggregated diagnoses are found.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from data.circuit_benchmark import Circuit, circuit_from_json, eval_op  # noqa: E402


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
        if len(ins) != 2:
            raise ValueError("XOR encoder expects two inputs")
        a, b = ins
        return [[gneg, -a, -b, -out], [gneg, -a, b, out], [gneg, a, -b, out], [gneg, a, b, -out]]
    raise ValueError(f"unsupported op {op}")


def build_observation_formula(
    circuit: Circuit,
    observation: dict,
    obs_idx: int,
) -> tuple[list[Clause], dict[str, int], dict[int, str], int]:
    pool = VarPool()
    healthy = {gate.name: pool.id(f"h::{gate.name}") for gate in circuit.gates}
    hard: list[Clause] = []

    def v(name: str) -> int:
        return pool.id(f"o{obs_idx}::{name}")

    for name, value in observation["inputs"].items():
        hard.append([v(name) if value else -v(name)])
    for gate in circuit.gates:
        hard.extend(guarded_equiv_clauses(gate.op, v(gate.name), [v(name) for name in gate.inputs], healthy[gate.name]))
    for name, value in observation["expected_outputs"].items():
        hard.append([v(name) if value else -v(name)])
    return hard, healthy, {lit: name for name, lit in healthy.items()}, pool.top


def semantic_diagnosis_valid(circuit: Circuit, observation: dict, diagnosis: set[str]) -> bool:
    disabled = list(diagnosis)
    for bits in itertools.product([False, True], repeat=len(disabled)):
        free_values = dict(zip(disabled, bits))
        values = dict(observation["inputs"])
        for gate in circuit.gates:
            if gate.name in free_values:
                values[gate.name] = free_values[gate.name]
            else:
                values[gate.name] = eval_op(gate.op, [values[name] for name in gate.inputs])
        if all(values[name] == expected for name, expected in observation["expected_outputs"].items()):
            return True
    return False


def semantic_core(circuit: Circuit, observation: dict, healthy_gate_names: list[str]) -> set[str]:
    """Deletion-minimize a core with exact semantic checks for small circuits."""
    core = set(healthy_gate_names)
    changed = True
    while changed:
        changed = False
        for gate_name in list(core):
            candidate = core - {gate_name}
            disabled = {gate.name for gate in circuit.gates if gate.name not in candidate}
            if not semantic_diagnosis_valid(circuit, observation, disabled):
                core = candidate
                changed = True
    return core


def check_observation(
    formula: tuple[list[Clause], dict[str, int], dict[int, str], int],
    circuit: Circuit,
    observation: dict,
    delta: set[str],
    solver: str,
) -> tuple[bool, set[str] | None, str]:
    clauses, healthy, names, _ = formula
    healthy_assumptions = [lit for name, lit in healthy.items() if name not in delta]
    if solver in {"auto", "pysat"}:
        try:
            from pysat.solvers import Solver

            with Solver(name="g3", bootstrap_with=clauses) as sat:
                status = bool(sat.solve(assumptions=healthy_assumptions))
                if status:
                    return True, None, "pysat_g3"
                core = sat.get_core() or healthy_assumptions
                return False, {names[lit] for lit in core if lit in names}, "pysat_g3"
        except ModuleNotFoundError:
            if solver == "pysat":
                raise

    if semantic_diagnosis_valid(circuit, observation, delta):
        return True, None, "semantic"
    core = semantic_core(circuit, observation, [name for name in healthy if name not in delta])
    return False, core, "semantic"


def minimum_hitting_set(
    cores: list[set[str]],
    diagnoses: list[set[str]],
    gate_names: list[str],
    min_size: int = 0,
) -> set[str] | None:
    start_size = max(min_size, 0)
    for size in range(start_size, len(gate_names) + 1):
        for combo in itertools.combinations(gate_names, size):
            candidate = set(combo)
            if any(diagnosis <= candidate for diagnosis in diagnoses):
                continue
            if all(candidate & core for core in cores):
                return candidate
    return None


def diagnose_hsd(
    circuit: Circuit,
    observations: list[dict],
    solver: str = "auto",
    enumerate_all: bool = True,
) -> dict:
    start = time.perf_counter()
    formulas = [build_observation_formula(circuit, observation, idx) for idx, observation in enumerate(observations)]
    gate_names = [gate.name for gate in circuit.gates]
    cores: list[set[str]] = []
    diagnoses: list[set[str]] = []
    optimum: int | None = None
    solver_used = "unknown"
    iterations = 0
    oracle_calls = 0

    while True:
        delta = minimum_hitting_set(cores, diagnoses, gate_names, min_size=optimum or 0)
        if delta is None:
            break
        if optimum is not None and len(delta) > optimum:
            break
        iterations += 1
        all_consistent = True
        for formula, observation in zip(formulas, observations):
            oracle_calls += 1
            status, core, solver_used = check_observation(formula, circuit, observation, delta, solver)
            if not status:
                if not core:
                    raise RuntimeError("HSD found an empty unsat core; no diagnosis exists")
                if core not in cores:
                    cores.append(core)
                all_consistent = False
                break
        if not all_consistent:
            continue
        if optimum is None:
            optimum = len(delta)
        diagnoses.append(delta)
        if not enumerate_all:
            break

    return {
        "solver": solver_used,
        "diagnoses": [sorted(diagnosis) for diagnosis in diagnoses],
        "diagnosis_count": len(diagnoses),
        "optimum_cost": optimum,
        "num_observations": len(observations),
        "num_gates": len(circuit.gates),
        "hsd_iterations": iterations,
        "oracle_calls": oracle_calls,
        "core_count": len(cores),
        "elapsed_sec": time.perf_counter() - start,
    }


def run_baseline(benchmark: Path, out: Path, limit: int = 0, solver: str = "auto", first_only: bool = False) -> None:
    manifest = json.loads((benchmark / "manifest.json").read_text())
    selected = manifest["instances"][: limit or None]
    results = {"method": "hsd", "benchmark": manifest["name"], "instances": []}
    for entry in selected:
        instance = json.loads((benchmark / entry["path"]).read_text())
        circuit = circuit_from_json(instance["faulty_circuit"])
        result = diagnose_hsd(circuit, instance["observations"], solver=solver, enumerate_all=not first_only)
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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=Path("data/synthetic_circuits"))
    parser.add_argument("--out", type=Path, default=Path("checkpoints/hsd_circuit/results.json"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--solver", choices=["auto", "pysat", "semantic"], default="auto")
    parser.add_argument("--first-only", action="store_true")
    args = parser.parse_args()
    run_baseline(args.benchmark, args.out, args.limit, args.solver, args.first_only)


if __name__ == "__main__":
    main()
