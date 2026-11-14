#!/bin/bash
# Reproduce the reference end to end (inside the compute container).
#
#   1. fetch the ISCAS85 netlists (no-op when present; needs internet once)
#   2. register the paper's method (CFaults) and score it on the train split
#   3. score every registered method on the hidden test split (if present)
#
# The evaluator-owned baseline outputs (HSD, BugAssist voting) are tracked in
# eval/train/baseline_outputs and eval/test/baseline_outputs; regenerate the
# train ones with scripts/baseline.sh.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

bash scripts/download.sh || echo "download skipped (offline); tracked data is sufficient for scoring"
bash scripts/method.sh
cp scoring/scores_train.json scoring/scores.json
if [ -f eval/test/evaluate_circuit_outputs.py ] && [ -f eval/test/hidden_benchmark.json.gz ]; then
  bash scripts/evaluate_test.sh
fi
