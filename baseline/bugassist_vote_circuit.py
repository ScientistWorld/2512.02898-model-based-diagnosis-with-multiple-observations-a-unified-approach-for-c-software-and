#!/usr/bin/env python3
"""BugAssist-style baseline: per-observation diagnosis plus frequency voting.

Algorithms 1-2 of the paper, transferred to circuits.  Each failing
observation is diagnosed on its own (single-replica MaxSAT; minimum-cost
correction sets enumerated with blocking clauses, capped per observation).
The diagnoses are ranked by how many observations produced them, ties broken
by size, and - as in the paper's experimental setup for BugAssist - the
highest-ranked diagnosis that is consistent with *all* observations is
returned (the top-ranked one if none is).  Exactly one diagnosis is written.

    python baseline/bugassist_vote_circuit.py --instance INSTANCE.json --output OUT.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

Clause = list[int]
PER_OBSERVATION_CAP = 50


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


def observation_formula(circuit: dict, observation: dict, health: dict[str, int]) -> tuple[list[Clause], int]:
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
    return clauses, nv


def per_observation_diagnoses(circuit: dict, observation: dict, health: dict[str, int]) -> list[frozenset[str]]:
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF

    clauses, nv = observation_formula(circuit, observation, health)
    wcnf = WCNF()
    for clause in clauses:
        wcnf.append(clause)
    for lit in health.values():
        wcnf.append([lit], weight=1)
    name_of = {lit: name for name, lit in health.items()}
    out: list[frozenset[str]] = []
    optimum = None
    with RC2(wcnf) as rc2:
        while len(out) < PER_OBSERVATION_CAP:
            model = rc2.compute()
            if model is None:
                break
            assigned = set(model)
            disabled = [lit for lit in health.values() if -lit in assigned]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum or not disabled:
                break
            out.append(frozenset(name_of[lit] for lit in disabled))
            rc2.add_clause(sorted(disabled))
    return out


def diagnose_vote(circuit: dict, observations: list[dict], max_checked: int = 200) -> list[str]:
    from pysat.solvers import Solver

    health = {gate["name"]: idx + 1 for idx, gate in enumerate(circuit["gates"])}
    votes: collections.Counter = collections.Counter()
    for obs in observations:
        votes.update(per_observation_diagnoses(circuit, obs, health))
    ranked = sorted(votes, key=lambda d: (-votes[d], len(d), sorted(d)))
    oracles = [Solver(name="g3", bootstrap_with=observation_formula(circuit, obs, health)[0]) for obs in observations]
    try:
        for diagnosis in ranked[:max_checked]:
            assumptions = [lit for name, lit in health.items() if name not in diagnosis]
            if all(oracle.solve(assumptions=assumptions) for oracle in oracles):
                return sorted(diagnosis)
    finally:
        for oracle in oracles:
            oracle.delete()
    return sorted(ranked[0]) if ranked else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    diagnosis = diagnose_vote(instance["circuit"], instance["observations"])
    with args.output.open("w") as out:
        out.write(json.dumps(diagnosis) + "\n")


if __name__ == "__main__":
    main()
