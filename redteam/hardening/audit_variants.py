#!/usr/bin/env python3
"""Honest diagnosis variants used to audit the hardened gym.

Each variant follows the evaluator interface (``--instance``/``--output``) and
uses only what a scientist sees: the method code and the public instance.

  incremental             CFaults (same unified MaxSAT, same Algorithm 5) but one
                          RC2Stratified oracle reused across blocked optima.
  satenum                 optimum k* from the unified MaxSAT, then all k*-subsets
                          enumerated by an incremental SAT solver under an
                          at-most-k* cardinality constraint (one SAT call each).
  weaker_one_observation  CFaults on the first failing observation only.
  first_only              CFaults returning only the first optimum.
  brute_force             every gate subset in increasing cardinality, each
                          checked by SAT against all observations, until the
                          first feasible cardinality is exhausted.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from method.cfaults_circuit import build_unified_formula, diagnose  # noqa: E402


def incremental(circuit, observations, emit):
    from pysat.examples.rc2 import RC2Stratified
    from pysat.formula import WCNF

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {v: k for k, v in healthy.items()}
    wcnf = WCNF()
    for clause in hard:
        wcnf.append(clause)
    for lit in soft:
        wcnf.append([lit], weight=1)
    optimum = None
    with RC2Stratified(wcnf) as solver:
        while True:
            model = solver.compute()
            if model is None:
                break
            assigned = set(model)
            disabled = [v for v in soft if -v in assigned]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum:
                break
            emit(sorted(names[v] for v in disabled))
            if not disabled:
                break
            solver.add_clause(disabled)


def satenum(circuit, observations, emit):
    from pysat.card import CardEnc, EncType
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF
    from pysat.solvers import Solver

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {v: k for k, v in healthy.items()}
    wcnf = WCNF()
    for clause in hard:
        wcnf.append(clause)
    for lit in soft:
        wcnf.append([lit], weight=1)
    with RC2(wcnf) as rc2:
        model = rc2.compute()
        assigned = set(model)
        first = [v for v in soft if -v in assigned]
    k = len(first)
    emit(sorted(names[v] for v in first))
    if k == 0:
        return
    card = CardEnc.atmost(lits=[-v for v in soft], bound=k, top_id=pool.top, encoding=EncType.seqcounter)
    with Solver(name="g4", bootstrap_with=hard + card.clauses) as sat:
        sat.add_clause(first)
        while sat.solve():
            assigned = set(sat.get_model())
            disabled = [v for v in soft if -v in assigned]
            emit(sorted(names[v] for v in disabled))
            sat.add_clause(disabled)


def brute_force(circuit, observations, emit):
    from pysat.solvers import Solver

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    items = list(healthy.items())
    with Solver(name="g3", bootstrap_with=hard) as sat:
        for size in range(len(items) + 1):
            hit = False
            for subset in itertools.combinations(range(len(items)), size):
                chosen = set(subset)
                assumptions = [-lit if i in chosen else lit for i, (_, lit) in enumerate(items)]
                if sat.solve(assumptions=assumptions):
                    emit(sorted(items[i][0] for i in subset))
                    hit = True
            if hit:
                return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("variant", choices=["incremental", "satenum", "weaker_one_observation", "first_only", "brute_force"])
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    circuit, observations = instance["circuit"], instance["observations"]
    with args.output.open("w") as out:

        def emit(diagnosis):
            out.write(json.dumps(diagnosis) + "\n")
            out.flush()

        if args.variant == "incremental":
            incremental(circuit, observations, emit)
        elif args.variant == "satenum":
            satenum(circuit, observations, emit)
        elif args.variant == "weaker_one_observation":
            diagnose(circuit, observations[:1], emit=emit)
        elif args.variant == "first_only":
            diagnose(circuit, observations, emit=emit, enumerate_all=False)
        else:
            brute_force(circuit, observations, emit)


if __name__ == "__main__":
    main()
