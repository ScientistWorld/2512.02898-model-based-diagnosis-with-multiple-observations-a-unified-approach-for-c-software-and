#!/usr/bin/env python3
"""HSD baseline: hitting-set dualisation for multi-observation diagnosis.

Algorithm 4 of the paper (Ignatiev et al.'s HSD, without core minimisation):

* one SAT oracle per observation, each holding that observation's circuit
  replica; gate health variables are passed as assumptions;
* a minimum hitting set Delta of the explanations (unsatisfiable cores)
  collected so far is computed with an incremental MaxSAT hitting-set solver
  (RC2), with every diagnosis found so far blocked;
* Delta is checked against the observations one at a time; the first
  inconsistent observation contributes its core as a new set to hit;
* a Delta consistent with all observations is a minimum-cardinality
  diagnosis; enumeration stops once the hitting-set size exceeds the optimum.

Same interface as the proposed method:

    python baseline/hsd_circuit.py --instance INSTANCE.json --output OUT.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

Clause = list[int]


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
        return [[gneg, -a, -b, -out], [gneg, -a, b, out], [gneg, a, -b, out], [gneg, a, b, -out]]
    raise ValueError(f"unsupported op {op}")


def observation_formula(circuit: dict, observation: dict, health: dict[str, int]) -> list[Clause]:
    """One replica P_i with observation o_i; health variables are 1..n."""
    nv = len(health)
    var: dict[str, int] = {}
    clauses: list[Clause] = []
    for name in circuit["inputs"]:
        nv += 1
        var[name] = nv
        clauses.append([nv if observation["inputs"][name] else -nv])
    for gate in circuit["gates"]:
        nv += 1
        var[gate["name"]] = nv
    for gate in circuit["gates"]:
        clauses.extend(guarded_equiv_clauses(gate["op"], var[gate["name"]], [var[x] for x in gate["inputs"]], health[gate["name"]]))
    for name, value in observation["expected_outputs"].items():
        clauses.append([var[name] if value else -var[name]])
    return clauses


def diagnose_hsd(circuit: dict, observations: list[dict], emit=None) -> list[list[str]]:
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF
    from pysat.solvers import Solver

    gate_names = [gate["name"] for gate in circuit["gates"]]
    health = {name: idx + 1 for idx, name in enumerate(gate_names)}
    name_of = {lit: name for name, lit in health.items()}
    oracles = [Solver(name="g3", bootstrap_with=observation_formula(circuit, obs, health)) for obs in observations]

    # Minimum hitting-set solver: x_g (variable id == health id) means g in Delta.
    hs = WCNF()
    for lit in health.values():
        hs.append([-lit], weight=1)
    hitter = RC2(hs)
    found: list[list[str]] = []
    optimum = None
    try:
        while True:
            model = hitter.compute()
            if model is None:
                break
            assigned = set(model)
            delta = [name for name in gate_names if health[name] in assigned]
            if optimum is not None and len(delta) > optimum:
                break
            in_delta = set(delta)
            assumptions = [health[name] for name in gate_names if name not in in_delta]
            consistent = True
            for oracle in oracles:
                if not oracle.solve(assumptions=assumptions):
                    core = [name_of[lit] for lit in (oracle.get_core() or []) if lit in name_of]
                    if not core:
                        raise RuntimeError("empty explanation: no diagnosis exists")
                    hitter.add_clause([health[name] for name in core])
                    consistent = False
                    break
            if not consistent:
                continue
            if optimum is None:
                optimum = len(delta)
            diagnosis = sorted(delta)
            found.append(diagnosis)
            if emit is not None:
                emit(diagnosis)
            if not delta:
                break
            hitter.add_clause([-health[name] for name in delta])  # block Delta and supersets
    finally:
        hitter.delete()
        for oracle in oracles:
            oracle.delete()
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    with args.output.open("w") as out:

        def emit(diagnosis: list[str]) -> None:
            out.write(json.dumps(diagnosis) + "\n")
            out.flush()

        diagnose_hsd(instance["circuit"], instance["observations"], emit=emit)


if __name__ == "__main__":
    main()
