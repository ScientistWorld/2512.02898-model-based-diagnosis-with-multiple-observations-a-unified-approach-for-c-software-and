#!/usr/bin/env python3
"""Artifact/data shortcuts: no evaluator or Python-environment tampering."""
import argparse
import copy
import json
from pathlib import Path


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2)+'\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('shortcut')
    args = p.parse_args()
    name = args.shortcut
    bench = Path('data/synthetic_circuits')
    manifest = json.loads((bench/'manifest.json').read_text())
    path = Path('checkpoints/cfaults_circuit/results.json')
    artifact = json.loads(path.read_text()) if path.exists() else {'instances': []}
    old = {x['id']: x for x in artifact['instances']}
    rows = []
    golden = json.loads((bench/manifest['circuit']).read_text())
    golden_ops = {x['name']: x['op'] for x in golden['gates']}
    perfect = []
    for entry in manifest['instances']:
        ipath = bench/entry['path']
        instance = json.loads(ipath.read_text())
        row = copy.deepcopy(old.get(instance['id'], {'id': instance['id']}))
        if name == 'label_copy_shortcut':
            row.update(diagnoses=[instance['faults']], solver_oracle_calls=0)
        elif name == 'golden_diff_shortcut':
            faults = [g['name'] for g in instance['faulty_circuit']['gates']
                      if golden_ops[g['name']] != g['op']]
            row.update(diagnoses=[faults], solver_oracle_calls=0)
        elif name == 'duplicate_diagnosis_shortcut':
            row['diagnoses'] = [diag+diag for diag in row['diagnoses']]
        elif name == 'negative_work_shortcut':
            row['solver_oracle_calls'] = -1000000000000
            row['elapsed_sec'] = -1000000000000
        elif name == 'zero_work_shortcut':
            row['solver_oracle_calls'] = 0
        elif name == 'all_gates_shortcut':
            row.update(diagnoses=[[g['name'] for g in instance['faulty_circuit']['gates']]],
                       solver_oracle_calls=0)
        elif name == 'constant_gate_shortcut':
            row.update(diagnoses=[['g0_sum']], solver_oracle_calls=0)
        elif name == 'empty_rows_shortcut':
            row.update(diagnoses=[], solver_oracle_calls=0)
        elif name == 'empty_artifact_shortcut':
            continue
        elif name == 'claimed_success_shortcut':
            row.update(diagnoses=[['NONEXISTENT_GATE']], solver_oracle_calls=0,
                       success=True, valid=True, minimal=True, optimum_cost=1,
                       elapsed_sec=-1000000000000, timeout=False)
        elif name == 'ground_truth_relabel_shortcut':
            instance['faults'] = row['diagnoses'][0]
            write(ipath, instance)
        elif name == 'test_subset_shortcut':
            if set(row['diagnoses'][0]) == set(instance['faults']):
                perfect.append(entry)
        rows.append(row)
    artifact['instances'] = rows
    write(path, artifact)
    if name == 'test_subset_shortcut':
        # Keep one entire setting whose last instance is solved exactly. The
        # public split rule leaves the last instance for test in this setting.
        target = next(e for e in perfect if e['path'].endswith('_002.json'))
        manifest['instances'] = [e for e in manifest['instances']
            if (e['fault_count'],e['observation_count']) ==
               (target['fault_count'],target['observation_count'])]
        write(bench/'manifest.json', manifest)
    if name == 'replace_baseline_shortcut':
        write(Path('checkpoints/hsd_circuit/results.json'), {'instances': []})
    if name == 'prewrite_scores_shortcut':
        write(Path('scoring/scores_test.json'), {'shortcut_marker': True,
              'experiments': {'iscas85_localisation': {'results': {'cfaults': {'selected_fault_f1': 1e99}}}}})


if __name__ == '__main__':
    main()
