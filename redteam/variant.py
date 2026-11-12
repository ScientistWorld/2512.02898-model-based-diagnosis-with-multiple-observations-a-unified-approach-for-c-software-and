#!/usr/bin/env python3
"""Real diagnostic variants. This file uses only scientist-visible modules/data."""
import argparse
import itertools
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from data.circuit_benchmark import circuit_from_json
from method.cfaults_circuit import build_unified_formula, diagnose


def incremental(circuit, observations):
    """Preserve the unified MaxSAT/all-optima algorithm, reuse solver state."""
    from pysat.examples.rc2 import RC2Stratified
    from pysat.formula import WCNF
    start = time.perf_counter()
    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = {v: k for k, v in healthy.items()}
    formula = WCNF()
    for clause in hard:
        formula.append(clause)
    for lit in soft:
        formula.append([lit], weight=1)
    solutions, optimum, calls = [], None, 0
    with RC2Stratified(formula) as solver:
        while True:
            calls += 1
            model = solver.compute()
            if model is None:
                break
            assigned = set(model)
            disabled = [v for v in soft if -v in assigned]
            if optimum is None:
                optimum = len(disabled)
            if len(disabled) > optimum:
                break
            solutions.append(sorted(names[v] for v in disabled))
            if not disabled:
                break
            solver.add_clause(disabled)
    return dict(diagnoses=solutions, optimum_cost=optimum,
                solver_oracle_calls=calls, elapsed_sec=time.perf_counter()-start)


def brute_force(circuit, observations):
    """Enumerate every gate subset through the first feasible cardinality."""
    from pysat.solvers import Solver
    start = time.perf_counter()
    hard, soft, pool, healthy = build_unified_formula(circuit, observations)
    names = list(healthy)
    solutions, calls = [], 0
    with Solver(name='g3', bootstrap_with=hard) as solver:
        for size in range(len(names)+1):
            for subset in itertools.combinations(names, size):
                disabled = set(subset)
                calls += 1
                if solver.solve(assumptions=[-v if k in disabled else v
                                             for k, v in healthy.items()]):
                    solutions.append(sorted(subset))
            if solutions:
                break
    return dict(diagnoses=solutions, optimum_cost=size, solver_oracle_calls=calls,
                elapsed_sec=time.perf_counter()-start)


def features(circuit):
    fanout = Counter(n for g in circuit.gates for n in g.inputs)
    return {g.name: (g.op, len(g.inputs), min(fanout[g.name], 4), g.name in circuit.outputs)
            for g in circuit.gates}


def learn_prior(instances):
    # The public train split is the ONLY source of training labels used here.
    from eval.train.evaluate_circuit_outputs import split_instance_ids
    train_ids = set(split_instance_ids({x['id']: x for x in instances}))
    counts = defaultdict(lambda: [1.0, 1.0])
    for instance in instances:
        if instance['id'] not in train_ids:
            continue
        circuit = circuit_from_json(instance['faulty_circuit'])
        for name, feats in features(circuit).items():
            for j, val in enumerate(feats):
                counts[(j, val)][int(name in instance['faults'])] += 1
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('variant')
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    random.seed(args.seed)
    bench = Path('data/synthetic_circuits')
    manifest = json.loads((bench/'manifest.json').read_text())
    instances = [json.loads((bench/e['path']).read_text()) for e in manifest['instances']]
    prior = learn_prior(instances) if args.variant == 'trained_tiebreak' else None
    rows = []
    for instance in instances:
        circuit = circuit_from_json(instance['faulty_circuit'])
        observations = instance['observations']
        if args.variant == 'incremental':
            row = incremental(circuit, observations)
        elif args.variant == 'brute_force':
            row = brute_force(circuit, observations)
        elif args.variant == 'weaker_one_observation':
            row = diagnose(circuit, observations[:1], solver='pysat')
        else:
            row = diagnose(circuit, observations, solver='pysat')
        if args.variant == 'trained_tiebreak':
            # Learn categorical mutation priors, then rank ONLY validated joint
            # minimum diagnoses. No golden netlist, test label, or seed lookup.
            feats = features(circuit)
            def merit(diag):
                return sum(math.log(prior[(j, value)][1]/prior[(j, value)][0])
                           for name in diag for j, value in enumerate(feats[name]))
            row['diagnoses'].sort(key=lambda d: (-merit(d), d))
        row['id'] = instance['id']
        rows.append(row)
    target = Path('checkpoints/cfaults_circuit/results.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'method': args.variant, 'seed': args.seed, 'instances': rows}, indent=2)+'\n')


if __name__ == '__main__':
    main()
