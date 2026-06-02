# Evaluation Targets

## Primary: iscas85_localisation

Tests whether a method can successfully localise faults on the augmented ISCAS85 Boolean-circuit benchmark across all observation-count settings.

- **Metric:** `localized_rate` (higher is better)
- **Supporting metrics:** `localized_count` (higher is better), `timeout_count` (lower is better), `memout_count` (lower is better)
- **How to run:** Evaluate every method on the same generated faulty ISCAS85 circuit instances with the same failing input-output observations and an 1800 second timeout per circuit.

## Constraint: diagnosis_quality

Tests whether reported fault sets are valid explanations of all failing observations and satisfy the benchmark's minimality requirement.

- **Metric:** `valid_minimal_rate` (higher is better)
- **Supporting metrics:** `invalid_count` (lower is better), `nonminimal_count` (lower is better)
- **How to run:** Independently validate each returned diagnosis against every failing observation for the instance, and check minimum-cardinality or subset-minimality according to the reproduced benchmark oracle.

## Constraint: observation_scaling

Tests whether localisation remains effective as the number of failing observations increases.

- **Metric:** per-group localisation rates `localized_rate_obs10`, `localized_rate_obs20`, `localized_rate_obs30`, `localized_rate_obs40`, and `localized_rate_obs50` (higher is better)
- **Supporting metrics:** per-group localised counts (higher is better)
- **How to run:** Report separate results for the 10, 20, 30, 40, and 50 failing-observation groups, using the same timeout and validation rules as the main benchmark.

## Constraint: runtime_efficiency

Tests whether successful diagnosis is obtained within practical compute limits.

- **Metric:** `relative_runtime_rank` (lower is better)
- **Supporting metrics:** `timeout_seconds` (lower is better when benchmark policy changes)
- **How to run:** Record CPU time for each circuit run under the benchmark timeout and compare runtime only on common successfully localised instances when making pairwise method comparisons.
