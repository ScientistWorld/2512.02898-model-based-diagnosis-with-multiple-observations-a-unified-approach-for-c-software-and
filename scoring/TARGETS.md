# Evaluation Targets

Every target is computed by `scripts/evaluate_test.sh` (hidden test, 158 instances) and `scripts/evaluate_train.sh` (public train split, 78 instances).

- Both evaluators run every method registered under `checkpoints/<name>/solver.json`, instance by instance.
- Each instance has a budget of 3x10^10 user-space instructions, counted by the evaluator over the method's whole process tree.
- Only the raw diagnoses written to the output file while the counted work was within budget are scored.
- Reference values come from the official hidden-test run, with train values in brackets.

## Primary: iscas85_localisation (weight 0.25)

The share of base-tier instances whose complete set of minimum-cardinality diagnoses was reported within the budget, and nothing else. The base tier is c880, c1355, c1908, c2670 and c3540, with 3, 5 or 7 faults and 10 to 50 observations (136 hidden instances).

- **Metric:** `localized_rate` (higher is better, coefficient 1.0). Reference 50.0 [40.3]; HSD 77.9 [68.7]; BugAssist voting 0.0.
- **Also ranked:** `min_diagnosis_recall` (higher, 0.5). Reference 65.3 [59.7].
- **Audit only:** `localized_count`, `total_instances`, `budget_stop_count`, `error_count`, `selected_fault_f1`, `exact_fault_set_rate`, `audit_avg_cpu_seconds`, `audit_mean_giga_instructions`, `failed_run`, `tamper_detected`.

## Constraint: diagnosis_quality (weight 0.15)

The share of all instances (both tiers) on which the method reported anything that is not a minimum-cardinality diagnosis. That covers a diagnosis inconsistent with some observation, one larger than the minimum, a malformed line, an unknown gate, or a duplicate. Such instances also score 0 everywhere else.

- **Metric:** `unsound_output_rate` (lower is better, coefficient 1.0). Reference 0.0 [0.0]; HSD 0.0; BugAssist voting 54.4.
- **Audit only:** `sound_output_rate`, `unsound_count`, `invalid_count`, `not_minimum_count`, `malformed_count`, `duplicate_count`, `over_limit_count`.

## observation_scaling (weight 0.10)

`localized_rate` on the base-tier instances with 10, 20, 30, 40 and 50 observations (25 to 28 hidden instances each).

- **Metrics:** `localized_rate_obs10` … `localized_rate_obs50` (higher, 0.2 each). Reference 67.9 / 63.0 / 46.4 / 42.9 / 28.0; HSD 92.9 / 85.2 / 75.0 / 67.9 / 68.0.
- **Audit only:** `min_diagnosis_recall_obs*`, `localized_count_obs*`.

## fault_scaling (weight 0.10)

`localized_rate` on the base-tier instances with 3, 5 and 7 injected faults (50, 48 and 38 hidden instances).

- **Metrics:** `localized_rate_f3` (higher, 0.2), `localized_rate_f5` (0.4), `localized_rate_f7` (0.4). Reference 74.0 / 41.7 / 28.9 [60.0 / 34.8 / 21.1]; HSD 94.0 / 75.0 / 60.5.
- **Audit only:** `min_diagnosis_recall_f*`, `localized_count_f*`.

## scale_stress (weight 0.25)

The two largest ISCAS85 circuits, c5315 and c7552, with 3, 5 or 7 faults and 10, 30 or 50 observations (22 hidden and 11 public instances). Budget and scoring are the same as the main experiment.

- **Metric:** `localized_rate_stress` (higher, 1.0). Reference 40.9 [45.5]; HSD 68.2 [90.9]; BugAssist voting 4.5.
- **Also ranked:** `min_diagnosis_recall_stress` (higher, 0.5). Reference 56.8 [64.2].
- **Audit only:** `localized_count_stress`, `total_instances_stress`, `budget_stop_count_stress`, `localized_rate_stress_f3`, `localized_rate_stress_f5`, `localized_rate_stress_f7`.

## runtime_profile (weight 0.15)

The share of all instances (both tiers) localised within one half, one quarter and one eighth of the budget. These are read from the same run, from the counted work at which each diagnosis appeared in the output.

- **Metrics:** `localized_rate_half_budget`, `localized_rate_quarter_budget`, `localized_rate_eighth_budget` (higher, 1/3 each). Reference 39.2 / 22.8 / 11.4 [33.3 / 19.2 / 10.3]; HSD 61.4 / 45.6 / 28.5.
- **Audit only:** `localized_count_*_budget`, `localized_rate_full_budget`, `total_instances_all`.

## Failure rules

A run that writes no output on any instance, or that changes the hidden test directory, receives the worst value of every metric above (0% rates, 100% unsound). An unregistered or invalid registration counts as a run with no output.
