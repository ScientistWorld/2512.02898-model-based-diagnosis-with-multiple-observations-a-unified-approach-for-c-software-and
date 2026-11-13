# Evaluation Targets

Every target is computed by `scripts/evaluate_test.sh` (hidden test, 118 instances) and `scripts/evaluate_train.sh` (public train split, 96 instances). Both evaluators run every method registered under `checkpoints/<name>/solver.json` instance by instance, under the per-instance CPU budget (nominal 10 CPU-s × machine-speed factor; whole process tree), and score only the raw diagnoses written. Reference values are from the official hidden-test run, with train values in brackets.

## Primary: iscas85_localisation (weight 0.25)

Share of base-tier instances (c432, c499, c880, c1355, c1908; 1/3/5 faults; 10-50 observations; 75 instances) whose complete set of minimum-cardinality diagnoses is reported, and nothing else, within the budget.

- **Metric:** `localized_rate` (higher is better, coefficient 1.0). Reference 97.33 [96.0]; HSD 100.0; BugAssist voting 10.67.
- **Also ranked:** `min_diagnosis_recall` (higher, 0.5). Reference 99.24 [99.02].
- **Audit only:** `localized_count`, `total_instances`, `cpu_limit_count`, `error_count`, `selected_fault_f1`, `exact_fault_set_rate`, `audit_avg_cpu_seconds`, `failed_run`, `tamper_detected`.

## Constraint: diagnosis_quality (weight 0.15)

Share of all instances (both tiers) on which the method reported anything that is not a minimum-cardinality diagnosis: a diagnosis inconsistent with some observation, one larger than the minimum, a malformed line, an unknown gate, or a duplicate. Such instances also score 0 everywhere else.

- **Metric:** `unsound_output_rate` (lower is better, coefficient 1.0). Reference 0.0 [0.0]; HSD 0.0; BugAssist voting 43.2.
- **Audit only:** `sound_output_rate`, `unsound_count`, `invalid_count`, `not_minimum_count`, `malformed_count`, `duplicate_count`, `over_limit_count`.

## observation_scaling (weight 0.10)

`localized_rate` on the base-tier instances with 10, 20, 30, 40 and 50 observations (15 instances each).

- **Metrics:** `localized_rate_obs10` … `localized_rate_obs50` (higher, 0.2 each). Reference 100 / 100 / 100 / 86.7 / 100.
- **Audit only:** `min_diagnosis_recall_obs*`, `localized_count_obs*`.

## fault_scaling (weight 0.10)

`localized_rate` on the base-tier instances with 1, 3 and 5 injected faults (25 instances each).

- **Metrics:** `localized_rate_f1` (higher, 0.2), `localized_rate_f3` (0.4), `localized_rate_f5` (0.4). Reference 100 / 96 / 96 [100 / 100 / 88].
- **Audit only:** `min_diagnosis_recall_f*`, `localized_count_f*`.

## scale_stress (weight 0.40)

The larger ISCAS85 circuits (c2670, c3540, c5315, c7552; 3/5 faults; 10/30/50 observations; 43 hidden and 21 public instances), with the same budget and scoring.

- **Metric:** `localized_rate_stress` (higher, 1.0). Reference 67.44 [66.67]; HSD 90.70; BugAssist voting 2.33.
- **Also ranked:** `min_diagnosis_recall_stress` (higher, 0.5). Reference 76.52 [75.38].
- **Audit only:** `localized_count_stress`, `total_instances_stress`, `cpu_limit_count_stress`, `localized_rate_stress_f3`, `localized_rate_stress_f5`.

## Failure rules

A run that writes no output on any instance, or that changes the hidden test directory, receives the worst value of every metric above (0% rates, 100% unsound). An unregistered or invalid registration counts as a run with no output.
