#!/usr/bin/env python3
"""CFaults for Boolean circuits: unified multi-observation MaxSAT diagnosis.

Implements the circuit side of the paper (Sections 4.2 and 5.2, Algorithm 5):

* the faulty circuit is unrolled once per failing observation (fresh wire
  variables per replica, inputs and expected outputs fixed as hard units);
* every gate is instrumented with ONE relaxation ("healthy") variable that is
  shared by all replicas: ``h_g -> (out_g <-> op_g(inputs_g))`` in each replica;
* soft unit clauses ``h_g`` (unweighted partial MaxSAT) maximise healthy gates;
* RC2Stratified (PySAT) is the MaxSAT oracle;
* all optimum solutions are enumerated by adding the blocking clause
  ``OR_{g in Delta} h_g`` to the hard clauses and re-solving until the cost
  exceeds the optimum.  As in the authors' CFaults tool (``oracle.py``,
  ``enumerate_MaxSATsolutions``), ONE RC2Stratified oracle is kept for the
  whole enumeration: each blocking clause is added to it with
  ``add_clause`` and ``compute`` is called again.

Interface (used by the train and hidden-test evaluators):

    python method/cfaults_circuit.py --instance INSTANCE.json --output OUT.jsonl

``INSTANCE.json`` holds ``circuit`` (inputs, outputs, gates in topological
order with ops AND/NAND/OR/NOR/XOR/NOT/BUF) and ``observations`` (input
values and expected output values).  Every minimum-cardinality diagnosis is
written to ``OUT.jsonl`` as one JSON list of gate names per line, flushed as
soon as it is found.

``python method/cfaults_circuit.py --register`` writes the registration file
``checkpoints/cfaults_circuit/solver.json`` that the evaluators read.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

Clause = list[int]
REPO_ROOT = Path(__file__).resolve().parents[1]


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
    """CNF for guard -> (out <-> op(ins))."""
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
        return [
            [gneg, -a, -b, -out],
            [gneg, -a, b, out],
            [gneg, a, -b, out],
            [gneg, a, b, -out],
        ]
    raise ValueError(f"unsupported op {op}")


def build_unified_formula(circuit: dict, observations: list[dict]) -> tuple[list[Clause], list[int], VarPool, dict[str, int]]:
    """Hard clauses: all observation replicas; soft literals: shared h_g."""
    pool = VarPool()
    healthy = {gate["name"]: pool.id(f"h::{gate['name']}") for gate in circuit["gates"]}
    hard: list[Clause] = []
    for obs_idx, obs in enumerate(observations):

        def v(name: str) -> int:
            return pool.id(f"o{obs_idx}::{name}")

        for name in circuit["inputs"]:
            hard.append([v(name) if obs["inputs"][name] else -v(name)])
        for gate in circuit["gates"]:
            out = v(gate["name"])
            ins = [v(name) for name in gate["inputs"]]
            hard.extend(guarded_equiv_clauses(gate["op"], out, ins, healthy[gate["name"]]))
        for name, value in obs["expected_outputs"].items():
            hard.append([v(name) if value else -v(name)])
    return hard, list(healthy.values()), pool, healthy


def diagnose(circuit: dict, observations: list[dict], emit=None, enumerate_all: bool = True) -> list[list[str]]:
    """Algorithm 5: enumerate all minimum-cardinality aggregated diagnoses."""
    from pysat.examples.rc2 import RC2Stratified
    from pysat.formula import WCNF

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {lit: name for name, lit in healthy.items()}
    wcnf = WCNF()
    for clause in hard:
        wcnf.append(clause)
    for lit in soft:
        wcnf.append([lit], weight=1)
    wcnf.nv = max(pool.top, wcnf.nv)
    optimum = None
    found: list[list[str]] = []
    with RC2Stratified(wcnf) as solver:
        while True:
            model = solver.compute()  # SolveMaxSAT(phi_H, phi_S)
            if model is None:
                break
            assigned = set(model)
            disabled = [lit for lit in soft if -lit in assigned]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum:
                break  # all optimum MaxSAT solutions enumerated
            diagnosis = sorted(names[lit] for lit in disabled)
            found.append(diagnosis)
            if emit is not None:
                emit(diagnosis)
            if not enumerate_all or not disabled:
                break
            solver.add_clause(sorted(disabled))  # blocking clause: OR_{g in Delta} h_g added to phi_H
    return found


def register(key_dir: str = "cfaults_circuit", extra_args: list[str] | None = None) -> Path:
    path = REPO_ROOT / "checkpoints" / key_dir / "solver.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["python", "method/cfaults_circuit.py", "--instance", "{instance}", "--output", "{output}"]
    command += extra_args or []
    path.write_text(json.dumps({"command": command}, indent=2) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--first-only", action="store_true", help="stop after the first optimum (ablation)")
    parser.add_argument("--register", action="store_true", help="write checkpoints/cfaults_circuit/solver.json")
    args = parser.parse_args()
    if args.register:
        print(register())
        return
    if args.instance is None or args.output is None:
        parser.error("--instance and --output are required")
    instance = json.loads(args.instance.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as out:

        def emit(diagnosis: list[str]) -> None:
            out.write(json.dumps(diagnosis) + "\n")
            out.flush()

        diagnose(instance["circuit"], instance["observations"], emit=emit, enumerate_all=not args.first_only)


if __name__ == "__main__":
    main()
