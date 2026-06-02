# Evaluation

## Metrics

The main metric is `localized_count`: the number of benchmark instances for which a method returns a valid minimum diagnosis before the timeout. `localized_rate` is the same count divided by the number of instances in the evaluated split. Higher is better for both.

The paper reports CPU time per circuit and aggregate timeout count. In this packaged gym, wall-clock time is recorded only as audit context because hardware varies across runs. Scored efficiency uses machine-independent proxies: whether the method completed within the fixed timeout/memory limits and the volume of reported diagnoses that must be checked.

Diagnosis quality is a constraint metric. A submitted diagnosis must be consistent with all failing input-output observations for that circuit and must be minimum-cardinality under the reproduced benchmark oracle. Invalid, non-minimal, or observation-inconsistent diagnoses should not count as successfully localised instances.

## Baselines and Targets

The primary benchmark is the augmented ISCAS85 Boolean-circuit benchmark used in the paper: 12,147 faulty circuit instances, generated with 10, 20, 30, 40, or 50 failing observations and 1, 2, 3, 4, 5, 10, 20, 30, 40, or 50 injected faults.

The paper compares the proposed circuit diagnosis system against HSD and HSD with core minimisation. Reported all-instance localisation rates are 73.84% for the paper method, 80.14% for HSD, and 79.67% for HSD-CM under an 1800 second timeout per circuit. A strong reproduction should recover the same qualitative result: competitive localisation coverage against HSD while preserving diagnosis validity/minimality, with HSD generally faster on circuits.

## Evaluation Protocol

Run each method on the same augmented ISCAS85 instances, grouped by the number of failing observations. Use the same input-output observations and injected-fault configurations for all methods. Use an 1800 second timeout per buggy circuit and record success, timeout, memory failure, and wall-clock time as non-scored audit fields.

For each returned diagnosis, independently validate that deactivating or repairing the reported components can satisfy all failing observations for that instance. Compute success counts and rates for each observation-count group and for the full benchmark. If the reproduction must scale down, keep the same procedure and include multiple observation-count groups plus multi-fault cases so the task remains non-trivial.
