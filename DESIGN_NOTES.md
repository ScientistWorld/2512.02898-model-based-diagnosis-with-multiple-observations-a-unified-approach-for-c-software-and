# Train/Test Evaluation Design Notes

> **Historical (iterations 1-9).** This note describes the earlier synthetic-circuit gym (artifact-based scoring, solver-call counts, injected-fault F1). It is superseded: the current benchmark, protocol and scores are in `briefing/`, `scoring/` and `HARDENING.md`.

Checked the train/test split scripts side by side. `scripts/evaluate_train.sh` invokes `eval/train/` and writes `scoring/scores_train.json`; `scripts/evaluate_test.sh` invokes `eval/test/` and writes `scoring/scores_test.json`. Both scripts enumerate result artifacts from the result root rather than hardcoding a method name. `bash -n` passes for both scripts, and no `scoring/scores_train.json` or `scoring/scores_test.json` stubs are present.

Checked evaluator attachment to methods. Both slices read method-produced `checkpoints/*/results.json` artifacts and do not import from `method/`, so future methods can change scores by changing their artifacts. The test evaluator optionally restricts to method names already scored on the train slice, which keeps final train/test comparisons aligned.

Changed the quality scoring to make shortcut behavior more visible. The evaluators now score `all_reported_valid_minimal_rate`, `exact_fault_set_rate`, `complete_output_rate`, `missing_count`, and `empty_diagnosis_count`. This catches methods that put one acceptable diagnosis first while dumping invalid extra diagnoses, omit hard instances, or return a valid but wrong injected-fault set.

Changed the efficiency scoring away from a hardware-tied runtime placeholder. The legacy `relative_runtime_rank` and `timeout_seconds` fields remain as zero-coefficient compatibility fields, while the scored train/test metrics are now `avg_reported_diagnoses_per_instance` and `max_reported_diagnoses_per_instance`. These are machine-independent and penalize artifact spam that can otherwise hide behind a correct first diagnosis.

Updated `scoring/reference.json` so all metric definitions include `higher_is_better`, `coefficient`, and `description`. Nonzero metrics do not measure agreement with paper values.

Runtime concerns for the next iteration: validating every reported diagnosis is intentionally stricter, but a malicious or very noisy artifact with many diagnoses could make evaluation slower. The output-volume metrics should discourage that, but the runner should watch for excessive validation time and consider a documented cap or streaming fail-fast policy if it becomes a practical issue.
