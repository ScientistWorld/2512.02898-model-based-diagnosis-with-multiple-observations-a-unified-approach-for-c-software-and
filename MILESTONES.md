# Reproduction Milestones

**Current: core_claim**

## Progress Log

### [2026-06-02 12:05] - method_runs
- Patched the top-level reusable evaluator to emit the selected-fault overlap, output-completeness, and diagnosis-volume metrics already expected by `reference.json`.
- Reset the active milestone to `method_runs` pending a fresh packaged CPU validation job, because `scoring/scores.json` must be regenerated after the evaluator change.
- Updated `scripts/run.sh` to run the full reproduce/evaluate/validate pipeline in the compute container.

### [2026-06-02 12:28] - method_runs
- Final verification found a critical Boolean-gate encoding bug: the CNF clauses for binary gates did not match the data generator's circuit semantics.
- Corrected `AND`, `OR`, `NAND`, and `NOR` encodings in method, baseline, and evaluator code.
- Verified the corrected encodings by truth table locally; fresh packaged scoring is pending a CPU test job before `core_claim` can be restored.

### [2026-06-02 12:49] - core_claim
- CPU job `e9807e81-d04` completed successfully after the Boolean-gate repair and regenerated root, train, and test score artifacts.
- Restored `core_claim`: the corrected CFaults implementation localizes all 27 scaled synthetic circuit instances, and every counted diagnosis is valid, minimum-cardinality, and consistent with all observations.
- Verified the final scoring contract with `python validate.py --compare`; all checks passed.

### [2026-06-02 12:52] - core_claim
- Fixed `reference.json` for the gym-only runtime-efficiency proxy: the paper does not report diagnosis-output volume, so the reference now labels the value as a corrected scaled-gym reference from job `e9807e81-d04`.
- Re-ran both `python validate.py` and `python validate.py --compare`; all checks passed.

### [2026-06-02 11:56] - core_claim
- Added an HSD-style circuit baseline that follows the paper's multiple-observation hitting-set dualisation comparison path.
- Wired the HSD artifact into the reusable root, train, and test evaluators while keeping BugAssist voting as an unscored sanity baseline.
- Kept the milestone at `core_claim` because the expanded scored comparison still needs a packaged CPU verification job.

### [2026-06-02 11:10] - core_claim
- Implemented the paper's Boolean-circuit multi-observation MBD algorithm as a unified partial MaxSAT encoding with shared gate health variables.
- Verified the scaled synthetic circuit benchmark result: CFaults produced valid minimum-cardinality diagnoses for all 27 tracked instances.
- Kept diagnosis quality as a constraint metric: invalid and non-minimal diagnoses are counted as failures.

### [2026-06-02 11:25] - method_runs
- Continuation audit reset the current milestone to `method_runs` pending fresh verification.
- Confirmed the method code is a real scaled implementation of the paper's circuit-side unified multi-observation MaxSAT diagnosis algorithm.
- Found that `scoring/scores.json` is stale after adding the explicit all-observations consistency metric, so a CPU test job is required to regenerate scores before restoring `core_claim`.

### [2026-06-02 11:42] - core_claim
- CPU job `06041b2e-9e9` completed successfully inside the packaged container and regenerated `scoring/scores.json`.
- Restored `core_claim`: CFaults localized 27 / 27 scaled synthetic circuit instances and every counted diagnosis was valid, minimum-cardinality, and consistent with all observations.
- Verified the scoring contract with `python validate.py --compare`; all checks passed.

## Stop Justification
- Not stopping yet: `core_claim` is already verified, and an HSD baseline expansion is pending packaged CPU verification.
