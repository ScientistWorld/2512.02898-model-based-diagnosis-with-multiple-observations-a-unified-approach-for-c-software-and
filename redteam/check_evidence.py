#!/usr/bin/env python3
"""Read saved audit evidence; perform no training, inference, or SAT solving."""
import json
from pathlib import Path

from harness import CASES

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def diagnosis_sets(path):
    return {r['id']: {tuple(sorted(d)) for d in r['diagnoses']}
            for r in read(path)['instances']}


def main():
    reference = read(HERE/'reference_seed_0/scores_test.json')
    config = read(HERE/'initial/scoring/reference.json')['experiments']
    summary = read(HERE/'summary.json')
    scored = [(e, m) for e, x in config.items() for m, spec in x['metrics'].items()
              if spec['coefficient']]
    assert len(scored) == 13
    assert reference['experiments'] == read(HERE/'initial/scoring/scores_test.json')['experiments']
    spreads, bounds = {}, []
    for e, m in scored:
        values = [read(HERE/f'reference_seed_{seed}/scores_test.json')
                  ['experiments'][e]['results']['cfaults'][m] for seed in range(3)]
        spreads[e+'/'+m] = max(values)-min(values)
        bound = 100 if config[e]['metrics'][m]['higher_is_better'] else 0
        if values[0] == bound:
            bounds.append(e+'/'+m)
    assert all(s == 0 for s in spreads.values())
    assert not bounds
    refsets = diagnosis_sets(HERE/'reference_seed_0/method_results.json')
    equal_sets = {name: diagnosis_sets(HERE/name/'method_results.json') == refsets
                  for name in ('incremental', 'trained_tiebreak', 'brute_force', 'hsd_honest_alternative')}
    assert all(equal_sets.values())
    ref_rank = summary['runs']['reference_seed_0']['rank_vs_reference']
    assert summary['runs']['trained_tiebreak']['rank_vs_reference'] > ref_rank
    assert summary['runs']['weaker_one_observation']['rank_vs_reference'] < ref_rank
    for name in CASES:
        meta = read(HERE/name/'run_metadata.json')
        assert meta['hidden_command'] == ['bash', 'scripts/evaluate_test.sh']
        assert meta['hidden_arguments'] == [] and meta['hidden_restored_after_method']
        assert all(event['returncode'] == 0 for event in meta['events'])
        read(HERE/name/'scores_test.json')
    padded = summary['runs']['nonminimal_padding_shortcut']
    assert padded['valid_minimal_rate'] == 0 and padded['all_observations_consistent_rate'] == 100
    assert padded['rank_vs_reference'] > 0
    assert summary['runs']['duplicate_diagnosis_shortcut']['rank_vs_reference'] == 0
    assert len(summary['runs']['empty_shortlist_shortcut']['missing_ranked_metrics']) == 13
    empty = read(HERE/'empty_shortlist_shortcut/scores_test.json')
    assert all(not ex['results'] for ex in empty['experiments'].values())
    late = read(HERE/'late_method_shortcut/run_metadata.json')
    assert 'checkpoints/late_method_shortcut/results.json' in late['result_files_on_disk']
    assert all('late_method_shortcut' not in names for names in late['scored_methods'].values())
    prewritten = read(HERE/'prewrite_scores_shortcut/scores_test.json')
    assert 'shortcut_marker' not in prewritten
    evidence = dict(
        cases_completed=len(CASES), ranked_metric_count=len(scored),
        fresh_reference_matches_original_test_experiments=True,
        scored_reference_best_bound_metrics=bounds, scored_seed_spreads=spreads,
        full_27_instance_diagnosis_sets_equal_reference=equal_sets,
        every_hidden_command_no_arguments_and_returned_zero=True,
        all_nonminimal_padding_outranks_reference=True,
        empty_shortlist_has_no_results_in_all_experiments=True,
        late_method_on_disk_omitted_from_all_experiments=True,
        prewritten_hidden_scores_overwritten=True)
    (HERE/'checks.json').write_text(json.dumps(evidence, indent=2, sort_keys=True)+'\n')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
