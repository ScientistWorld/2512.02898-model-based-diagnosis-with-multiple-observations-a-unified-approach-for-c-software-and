#!/usr/bin/env python3
"""Honest diagnosis variants used to audit the hardened gym.

Each variant follows the evaluator interface (``--instance``/``--output``) and
uses only what a scientist sees: the method code and the public instance.

  fresh_solver            the previous gym reference: CFaults with a NEW
                          RC2Stratified oracle for every blocked optimum (the
                          authors' tool reuses one oracle; see method/).
  lazy_observations       CFaults-family improvement: the unified MaxSAT is built
                          lazily, starting from one observation; every candidate
                          optimum is checked against the remaining observations
                          with per-observation SAT calls and the first violated
                          observation's replica is added to the unified formula.
  satenum                 optimum k* from the unified MaxSAT, then all k*-subsets
                          enumerated by an incremental SAT solver under an
                          at-most-k* cardinality constraint (one SAT call each).
  lean                    the paper's procedure exactly (unified MaxSAT, one
                          incremental RC2 oracle, blocking clauses), but each
                          optimum is read directly from the oracle's model for
                          the gate-health variables, instead of RC2.compute()'s
                          Python remapping and sorting of every variable of the
                          unified formula (O(#gates x #observations) per optimum).
  exhaust_minz            the reference with RC2's core exhaustion, core
                          minimisation and AtMost1 detection switched on.
  lean_exhaust_minz       both of the above.
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
from method.cfaults_circuit import build_unified_formula, diagnose, guarded_equiv_clauses  # noqa: E402


def fresh_solver(circuit, observations, emit):
    from pysat.examples.rc2 import RC2Stratified
    from pysat.formula import WCNF

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {v: k for k, v in healthy.items()}
    block, optimum = [], None
    while True:
        wcnf = WCNF()
        for clause in hard + block:
            wcnf.append(clause)
        for lit in soft:
            wcnf.append([lit], weight=1)
        wcnf.nv = max(pool.top, wcnf.nv)
        with RC2Stratified(wcnf) as solver:
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
        block.append(sorted(disabled))


def _replica(circuit, obs, health, offset):
    var, clauses, nv = {}, [], offset
    for name in circuit["inputs"]:
        nv += 1
        var[name] = nv
        clauses.append([nv if obs["inputs"][name] else -nv])
    for gate in circuit["gates"]:
        nv += 1
        var[gate["name"]] = nv
    for gate in circuit["gates"]:
        clauses.extend(guarded_equiv_clauses(gate["op"], var[gate["name"]], [var[x] for x in gate["inputs"]], health[gate["name"]]))
    for name, value in obs["expected_outputs"].items():
        clauses.append([var[name] if value else -var[name]])
    return clauses


def lean(circuit, observations, emit, **rc2_options):
    from pysat.examples.rc2 import RC2
    from pysat.formula import WCNF

    class LeanRC2(RC2):
        """Same core-guided search; returns the SAT oracle's raw model (internal ids)."""

        def compute_raw(self):
            return self.oracle.get_model() if self.compute_() else None

    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {lit: name for name, lit in healthy.items()}
    wcnf = WCNF()
    for clause in hard:
        wcnf.append(clause)
    for lit in soft:
        wcnf.append([lit], weight=1)
    wcnf.nv = max(pool.top, wcnf.nv)
    optimum = None
    with LeanRC2(wcnf, **rc2_options) as rc2:
        index = [(lit, rc2.vmap.e2i.get(lit, lit) - 1) for lit in soft]  # formula variables keep their ids
        while True:
            model = rc2.compute_raw()
            if model is None:
                break
            disabled = [lit for lit, i in index if model[i] < 0]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum:
                break
            emit(sorted(names[lit] for lit in disabled))
            if not disabled:
                break
            rc2.add_clause(sorted(disabled))


def exhaust_minz(circuit, observations, emit):
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
    with RC2Stratified(wcnf, adapt=True, exhaust=True, minz=True) as rc2:
        while True:
            model = rc2.compute()
            if model is None:
                break
            assigned = set(model)
            disabled = [lit for lit in soft if -lit in assigned]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum:
                break
            emit(sorted(names[lit] for lit in disabled))
            if not disabled:
                break
            rc2.add_clause(sorted(disabled))


def lazy_observations(circuit, observations, emit):
    from pysat.examples.rc2 import RC2Stratified
    from pysat.formula import WCNF
    from pysat.solvers import Solver

    gates = [g["name"] for g in circuit["gates"]]
    health = {name: i + 1 for i, name in enumerate(gates)}
    names = {v: k for k, v in health.items()}
    width = len(circuit["inputs"]) + len(gates)
    n = len(gates)
    replicas = [_replica(circuit, obs, health, n + i * width) for i, obs in enumerate(observations)]
    checkers = [Solver(name="g3", bootstrap_with=_replica(circuit, obs, health, n)) for obs in observations]
    wcnf = WCNF()
    for clause in replicas[0]:
        wcnf.append(clause)
    for lit in health.values():
        wcnf.append([lit], weight=1)
    wcnf.nv = n + len(observations) * width  # reserve ids of every replica before RC2 allocates its own
    used = {0}
    optimum = None
    try:
        with RC2Stratified(wcnf) as rc2:
            while True:
                model = rc2.compute()
                if model is None:
                    break
                assigned = set(model)
                disabled = [v for v in health.values() if -v in assigned]
                if optimum is not None and len(disabled) > optimum:
                    break
                off = set(disabled)
                assumptions = [v for v in health.values() if v not in off]
                bad = next((i for i in range(len(observations)) if i not in used
                            and not checkers[i].solve(assumptions=assumptions)), None)
                if bad is not None:
                    used.add(bad)
                    for clause in replicas[bad]:
                        rc2.add_clause(clause)
                    continue
                if optimum is None:
                    optimum = len(disabled)
                emit(sorted(names[v] for v in disabled))
                if not disabled:
                    break
                rc2.add_clause(sorted(disabled))
    finally:
        for c in checkers:
            c.delete()


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
    parser.add_argument("variant", choices=["fresh_solver", "lazy_observations", "satenum", "weaker_one_observation",
                                            "first_only", "brute_force", "lean", "exhaust_minz", "lean_exhaust_minz"])
    parser.add_argument("--instance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    instance = json.loads(args.instance.read_text())
    circuit, observations = instance["circuit"], instance["observations"]
    with args.output.open("w") as out:

        def emit(diagnosis):
            out.write(json.dumps(diagnosis) + "\n")
            out.flush()

        if args.variant == "fresh_solver":
            fresh_solver(circuit, observations, emit)
        elif args.variant == "lazy_observations":
            lazy_observations(circuit, observations, emit)
        elif args.variant == "satenum":
            satenum(circuit, observations, emit)
        elif args.variant == "weaker_one_observation":
            diagnose(circuit, observations[:1], emit=emit)
        elif args.variant == "first_only":
            diagnose(circuit, observations, emit=emit, enumerate_all=False)
        elif args.variant == "lean":
            lean(circuit, observations, emit)
        elif args.variant == "exhaust_minz":
            exhaust_minz(circuit, observations, emit)
        elif args.variant == "lean_exhaust_minz":
            lean(circuit, observations, emit, adapt=True, exhaust=True, minz=True)
        else:
            brute_force(circuit, observations, emit)


if __name__ == "__main__":
    main()
