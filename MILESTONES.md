# Reproduction Milestones

**Current: method_runs**

## Progress Log

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

## Stop Justification
- Not stopped. Submitting a CPU test job to regenerate scores after continuation audit.
