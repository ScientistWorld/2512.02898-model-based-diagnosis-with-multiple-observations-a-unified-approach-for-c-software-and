#!/usr/bin/env python3
"""Isolated, scientist-visible staging followed by the restored hidden test.

Hidden evaluation runs only AFTER all foreground method processes terminate.
No test arguments, evaluator edits, Python hooks, or environment overrides.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT/'redteam'
CASES = [
    'reference_seed_0', 'reference_seed_1', 'reference_seed_2',
    'incremental', 'trained_tiebreak', 'weaker_one_observation', 'brute_force',
    'hsd_honest_alternative',
    'label_copy_shortcut', 'golden_diff_shortcut',
    'duplicate_diagnosis_shortcut', 'zero_work_shortcut', 'negative_work_shortcut',
    'ground_truth_relabel_shortcut', 'test_subset_shortcut',
    'empty_artifact_shortcut', 'empty_rows_shortcut', 'all_gates_shortcut',
    'constant_gate_shortcut', 'claimed_success_shortcut',
    'replace_baseline_shortcut', 'prewrite_scores_shortcut',
    'late_method_shortcut', 'empty_shortlist_shortcut',
]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def copy_visible(work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for dirname in ('data', 'baseline', 'method'):
        shutil.copytree(ROOT/dirname, work/dirname,
                        ignore=shutil.ignore_patterns('__pycache__', 'downloads', '.gitkeep'))
    (work/'briefing').mkdir()
    for filename in ('problem.md', 'evaluation.md', 'method.md', 'overview.md'):
        shutil.copy2(ROOT/'briefing'/filename, work/'briefing'/filename)
    (work/'environment').mkdir()
    for filename in ('setup.sh', 'container.def'):
        shutil.copy2(ROOT/'environment'/filename, work/'environment'/filename)
    (work/'scripts').mkdir()
    for filename in ('baseline.sh', 'download.sh', 'evaluate_train.sh'):
        shutil.copy2(ROOT/'scripts'/filename, work/'scripts'/filename)
    (work/'scoring').mkdir()
    for filename in ('TARGETS.md', 'CONSTRAINTS.md', 'DIRECTION.md', 'EXPERIMENTS.md'):
        shutil.copy2(ROOT/'scoring'/filename, work/'scoring'/filename)
    shutil.copytree(ROOT/'eval/train', work/'eval/train',
                    ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(AUDIT/'variant.py', work/'method/audit_variant.py')
    shutil.copy2(AUDIT/'shortcut.py', work/'method/audit_shortcut.py')


def execute(case):
    out = AUDIT/case
    out.mkdir(parents=True, exist_ok=True)
    work = AUDIT/'workspaces'/case
    copy_visible(work)
    events = []
    with (out/'run.log').open('w') as log:
        def run(cmd, *, env=None):
            before = time.perf_counter()
            status = subprocess.run(cmd, cwd=work, stdout=log, stderr=subprocess.STDOUT,
                                    env=env, timeout=1800)
            events.append(dict(command=cmd, returncode=status.returncode,
                               wall_seconds=time.perf_counter()-before))
            if status.returncode:
                raise RuntimeError(f'{case}: command failed: {cmd}')

        # Reuse freshly generated reference artifacts only, never supplied hidden
        # scores/checkpoints. This is equivalent to the scientist saving its run.
        refdir = AUDIT/'reference_seed_0'
        cpath = work/'checkpoints/cfaults_circuit/results.json'
        hpath = work/'checkpoints/hsd_circuit/results.json'
        hpath.parent.mkdir(parents=True)
        if case == 'reference_seed_0':
            run(['python', 'baseline/hsd_circuit.py', '--solver', 'pysat'])
        else:
            shutil.copy2(refdir/'baseline_results.json', hpath)
        if case.startswith('reference_seed_'):
            seed = int(case.rsplit('_',1)[1])
            env = dict(os.environ, PYTHONHASHSEED=str(seed))
            run(['python', 'method/audit_variant.py', 'reference', '--seed', str(seed)], env=env)
        elif case == 'hsd_honest_alternative':
            cpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(refdir/'baseline_results.json', cpath)
        elif case in ('incremental', 'trained_tiebreak', 'weaker_one_observation', 'brute_force'):
            run(['python', 'method/audit_variant.py', case])
        else:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(refdir/'method_results.json', cpath)
            if case == 'empty_shortlist_shortcut':
                save(cpath, {'instances': []})
            else:
                run(['python', 'method/audit_shortcut.py', case])

        # Run public evaluation exactly as the scientist does.
        run(['bash', 'scripts/evaluate_train.sh'])
        if case == 'late_method_shortcut':
            late = work/'checkpoints/late_method_shortcut/results.json'
            late.parent.mkdir(parents=True)
            save(late, {'instances': []})
        elif case == 'empty_shortlist_shortcut':
            train = json.loads((work/'scoring/scores_train.json').read_text())
            for ex in train['experiments'].values():
                ex['results'] = {}
            save(work/'scoring/scores_train.json', train)

        # Simulate restoration: use the gym's pristine hidden evaluator/script,
        # installed only now. All other scientist-produced files stay in place.
        if (work/'eval').exists():
            shutil.rmtree(work/'eval')
        shutil.copytree(ROOT/'eval', work/'eval',
                        ignore=shutil.ignore_patterns('__pycache__', '.gitkeep'))
        shutil.copy2(ROOT/'scripts/evaluate_test.sh', work/'scripts/evaluate_test.sh')
        run(['bash', 'scripts/evaluate_test.sh'])
        shutil.copy2(work/'scoring/scores_test.json', out/'scores_test.json')
        shutil.copy2(work/'scoring/scores_train.json', out/'scores_train.json')
        shutil.copy2(cpath, out/'method_results.json')
        if case == 'reference_seed_0':
            shutil.copy2(hpath, out/'baseline_results.json')
        manifest = json.loads((work/'data/synthetic_circuits/manifest.json').read_text())
        method_files = sorted(str(p.relative_to(work)) for p in (work/'checkpoints').glob('*/results.json'))
        scored = json.loads((out/'scores_test.json').read_text())
        names = {k: sorted(v['results']) for k,v in scored['experiments'].items()}
        save(out/'run_metadata.json', dict(case=case, events=events, manifest_instances=len(manifest['instances']),
             result_files_on_disk=method_files, scored_methods=names,
             hidden_command=['bash', 'scripts/evaluate_test.sh'], hidden_arguments=[],
             visible_data_only=True, hidden_restored_after_method=True))
    print(f'Finished {case}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=CASES+['all'])
    args = parser.parse_args()
    if args.case == 'all':
        failures = {}
        for case in CASES:
            try:
                execute(case)
            except Exception as exc:
                failures[case] = str(exc)
                print(f'FAILED {case}: {exc}', flush=True)
        save(AUDIT/'job_failures.json', failures)
        if failures:
            raise SystemExit(1)
    else:
        execute(args.case)


if __name__ == '__main__':
    main()
