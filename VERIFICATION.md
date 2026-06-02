# Verification Report

## Initial Assessment

The workspace claimed `core_claim`, and earlier CPU job `e9807e81-d04` had verified the corrected CFaults implementation and regenerated root/train/test score artifacts. A later expansion added the HSD circuit baseline; CPU job `f183bdd9-60a` ran the expanded pipeline but failed validation because the runtime-efficiency primary metric tied across CFaults and HSD on the train slice.

## Issues Found

- Critical: `AND`, `OR`, `NAND`, and `NOR` encodings in the method, baseline, and evaluator were dualized relative to the data generator's gate semantics.
- Minor: evaluation documentation still described wall-clock CPU time as an efficiency metric. The gym should not score wall-clock speed across variable hardware.
- Minor: `runtime_efficiency.avg_reported_diagnoses_per_instance` was initially stored in `reference.json` without making clear that it is a scaled-gym proxy rather than a paper-reported value.
- Minor: after adding the HSD baseline, `runtime_efficiency.avg_reported_diagnoses_per_instance` tied across exact enumerators on the train split, so it could not rank methods as the primary metric.
- Minor limitation: the current benchmark is a scaled tracked synthetic circuit set rather than the full augmented ISCAS85 benchmark from the paper.
- Cosmetic/workspace: unrelated pre-existing root changes remain in `README.md`, `manifest.json`, and `trajectory/`; they were left untouched.

## Fixes Applied

- Corrected binary gate encodings in `method/`, `baseline/`, and `eval/`.
- Regenerated method outputs, baseline outputs, `scores.json`, `scores_train.json`, and `scores_test.json` in CPU job `e9807e81-d04`.
- Clarified evaluation documentation so wall-clock runtime is audit context only; scored efficiency uses timeout/memory outcomes and solver-oracle-call proxies.
- Updated `reference.json` so the diagnosis-output-volume proxy is explicitly documented as a corrected scaled-gym reference value from job `e9807e81-d04`.
- Added explicit `solver_oracle_calls` fields to CFaults and HSD artifacts, changed the runtime-efficiency primary metric to `avg_solver_oracle_calls_per_instance`, and kept diagnosis-output volume as audit-only.
- Re-ran `python validate.py` and `python validate.py --compare`; all checks passed.

## Final Judgment

The workspace remains at `core_claim` and local validation now passes after the runtime-efficiency scoring repair. A packaged CPU test job is being submitted to regenerate the score artifacts from scratch and confirm the patched CFaults/HSD scoring contract inside the container. The main limitation is scale: this demonstrates the core multi-observation circuit-diagnosis claim on a synthetic benchmark, not the full ISCAS85 study.

- Milestone: core_claim
- Ready for gym use: partial
- Confidence: medium
- Key limitation: packaged rerun pending after runtime-efficiency scoring repair; scaled synthetic circuit benchmark only
