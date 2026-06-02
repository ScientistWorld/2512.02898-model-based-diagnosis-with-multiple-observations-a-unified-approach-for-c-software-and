# Reproduction Milestones

**Current: core_claim**

## Progress Log

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

## Stop Justification
- Not stopped. Submitting a CPU test job to regenerate scores after scoring-schema cleanup.
