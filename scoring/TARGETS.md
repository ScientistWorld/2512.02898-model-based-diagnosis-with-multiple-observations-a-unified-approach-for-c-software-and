# Evaluation Targets

## Primary: iscas85_localisation

Tests whether a method can successfully localise faults on the augmented ISCAS85 Boolean-circuit benchmark across all observation-count settings.

- **Metric:** `selected_fault_f1` (higher is better)
- **Supporting metrics:** `exact_fault_set_rate`, `localized_rate`, `localized_count`, `timeout_count`, and `memout_count`
- **How to run:** Evaluate every method on the same generated faulty ISCAS85 circuit instances with the same failing input-output observations and an 1800 second timeout per circuit.

## Constraint: diagnosis_quality

Tests whether reported fault sets are valid explanations of all failing observations and satisfy the benchmark's minimum-cardinality requirement.

- **Metric:** `selected_fault_f1` (higher is better)
- **Supporting metrics:** `selected_fault_precision`, `selected_fault_recall`, `valid_minimal_rate`, `all_observations_consistent_rate`, `all_reported_valid_minimal_rate`, `complete_output_rate`, `avg_extra_gate_count`, `avg_missing_fault_count`, `invalid_count`, `nonminimal_count`, `missing_count`, and `empty_diagnosis_count`
- **How to run:** Independently validate each returned diagnosis against every failing observation for the instance, and check minimum-cardinality against the reproduced benchmark oracle.

## Constraint: observation_scaling

Tests whether localisation remains effective as the number of failing observations increases.

- **Metric:** per-group selected fault-set F1 scores `selected_fault_f1_obs10`, `selected_fault_f1_obs20`, `selected_fault_f1_obs30`, `selected_fault_f1_obs40`, and `selected_fault_f1_obs50` (higher is better)
- **Supporting metrics:** per-group exact fault-set rates, localisation rates, and localised counts
- **How to run:** Report separate results for the 10, 20, 30, 40, and 50 failing-observation groups, using the same timeout and validation rules as the main benchmark.

## Constraint: runtime_efficiency

Tests whether successful diagnosis is obtained without hiding behind excessive output volume.

- **Metric:** `avg_reported_diagnoses_per_instance` (lower is better)
- **Supporting metrics:** `max_reported_diagnoses_per_instance`, plus legacy `relative_runtime_rank` and `timeout_seconds` fields for paper-context compatibility
- **How to run:** Count the number of diagnoses emitted in each method artifact. Wall-clock timing is excluded from the train/test score because hardware varies across runners.
