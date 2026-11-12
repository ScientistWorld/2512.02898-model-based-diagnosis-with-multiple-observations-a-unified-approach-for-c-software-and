#!/usr/bin/env python3
"""Audit-cohort normalized ranks, with the user-specified ranking convention."""
import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def main():
    config = read(HERE/'initial/scoring/reference.json')['experiments']
    cases = {p.parent.name: read(p) for p in HERE.glob('*/scores_test.json')}
    baseline = cases['reference_seed_0']
    metrics = [(e, m, ex['weight']*abs(md['coefficient']), md['higher_is_better'])
               for e, ex in config.items() for m, md in ex['metrics'].items()
               if md['coefficient'] != 0]

    def get(case, exp, metric, method='cfaults'):
        return case.get('experiments',{}).get(exp,{}).get('results',{}).get(method,{}).get(metric)

    # Include HSD as one genuine baseline attempt; retain seeds and failed runs.
    cohort = list(cases.values())+[{'experiments': {e: {'results': {'cfaults': ex['results'].get('hsd',{})}}
                                                  for e,ex in baseline['experiments'].items()}}]
    scales = {}
    for e,m,w,high in metrics:
        vals = [get(c,e,m) for c in cohort if isinstance(get(c,e,m),(int,float))]
        scales[e+'/'+m] = statistics.pstdev(vals) if len(vals)>1 else 0

    results = {}
    for name,case in cases.items():
        rank, contributions, missing, dominates, regresses = 0.,{},[],True,False
        for e,m,w,high in metrics:
            val, ref = get(case,e,m), get(baseline,e,m)
            if val is None or ref is None:
                missing.append(e+'/'+m)
                continue
            gain = (val-ref)*(1 if high else -1)
            dominates = dominates and gain >= 0
            regresses = regresses or gain < 0
            sd = scales[e+'/'+m]
            contribution = w*gain/sd if sd else 0.
            contributions[e+'/'+m] = contribution
            rank += contribution
        loc = case['experiments']['iscas85_localisation']['results'].get('cfaults',{})
        qual = case['experiments']['diagnosis_quality']['results'].get('cfaults',{})
        runtime = case['experiments']['runtime_efficiency']['results'].get('cfaults',{})
        rows = read(HERE/name/'method_results.json').get('instances',[])
        testids = set(case['_evaluation_slice']['instance_ids'])
        results[name] = dict(rank_vs_reference=rank,
            selected_fault_f1=loc.get('selected_fault_f1'),
            localized_rate=loc.get('localized_rate'),
            valid_minimal_rate=qual.get('valid_minimal_rate'),
            all_observations_consistent_rate=qual.get('all_observations_consistent_rate'),
            avg_extra_gate_count=qual.get('avg_extra_gate_count'),
            avg_missing_fault_count=qual.get('avg_missing_fault_count'),
            avg_solver_calls=runtime.get('avg_solver_oracle_calls_per_instance'),
            max_solver_calls=runtime.get('max_solver_oracle_calls_per_instance'),
            test_instances=len(testids), missing_ranked_metrics=missing,
            weakly_dominates_on_present_metrics=dominates, has_regression=regresses,
            test_method_elapsed_seconds=sum(r.get('elapsed_sec',0) for r in rows if r['id'] in testids),
            contributions=contributions)

    seeds = [results[f'reference_seed_{n}'] for n in range(3)]
    spread = {key: max(s[key] for s in seeds)-min(s[key] for s in seeds)
              for key in ('rank_vs_reference','selected_fault_f1','valid_minimal_rate','avg_solver_calls')}
    doc = dict(rank_convention='sum(weight*abs(coefficient)*direction*(value-reference)/population_stddev_of_audit_cohort); missing skipped',
               reference='fresh reference_seed_0 cfaults, checked against original scores_test.json',
               scales=scales, seed_spread=spread, runs=results)
    (HERE/'summary.json').write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
    for name,r in results.items():
        print(name, 'rank=',round(r['rank_vs_reference'],6),
              'F1=',r['selected_fault_f1'], 'min=',r['valid_minimal_rate'],
              'calls=',r['avg_solver_calls'])


if __name__ == '__main__':
    main()
