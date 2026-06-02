# Scientist Constraints

## Data

Use the augmented ISCAS85 Boolean-circuit benchmark generated from the ISCAS85 circuits with the paper's fault and observation grid: 10, 20, 30, 40, and 50 failing observations, and 1, 2, 3, 4, 5, 10, 20, 30, 40, and 50 injected faults. Do not add external circuit benchmarks, extra observations, or easier synthetic circuits when reporting the main score. Extra datasets may be used only as clearly marked secondary analysis.

## Problem Formulation

Each benchmark instance must be solved as a circuit fault-localisation problem from failing input-output observations. A successful output is a set of circuit components/gates that explains all observations for that same faulty circuit. Do not replace the task with fault classification, learned ranking without validated diagnoses, single-observation-only diagnosis, or repair synthesis that does not identify the faulty components.

## Diagnosis Validity

A result counts as localised only if the returned diagnosis is consistent with all failing observations and satisfies the benchmark minimality criterion. Returning a superset of a valid diagnosis, a diagnosis valid for only some observations, or a ranked list without a validated top diagnosis must be counted as failure for `localized_count`.

## Evaluation Resources

Use the same timeout policy for all methods in the main comparison: 1800 seconds per buggy Boolean circuit. Record timeout and memory failures explicitly. Do not improve the headline score by giving one method more time, more memory, additional preprocessing data, or a different benchmark subset.

## Baseline Comparability

When comparing against HSD or HSD-CM, run all methods on the identical instances and observations. Runtime comparisons should be reported both overall and on the common set of successfully localised circuits, because coverage differences can otherwise distort speed claims.

## Compliance Checklist

- [ ] Main results use only the augmented ISCAS85 circuit instances
- [ ] Observation groups include the same 10, 20, 30, 40, and 50 settings
- [ ] Injected-fault settings include single-fault and multi-fault cases
- [ ] Each counted success has a diagnosis validated against all observations
- [ ] Non-minimal or observation-inconsistent diagnoses are counted as failures
- [ ] Timeout is 1800 seconds per buggy circuit for every compared method
- [ ] HSD/HSD-CM comparisons use the same instances as the submitted method
