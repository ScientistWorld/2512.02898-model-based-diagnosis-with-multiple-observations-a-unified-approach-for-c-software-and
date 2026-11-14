#!/bin/bash
# Regenerate the evaluator-owned baseline outputs on the PUBLIC train split.
#
# Baselines: HSD (hitting-set dualisation, the paper's circuit competitor) and
# a BugAssist-style per-observation voting baseline.  Their raw outputs are
# stored in eval/train/baseline_outputs/*.json.gz and scored by scripts/evaluate_train.sh
# under the keys "hsd" and "bugassist_vote".  (The hidden-test baseline
# outputs are stored with the hidden test and cannot be regenerated here.)
#
# Usage:
#   bash scripts/baseline.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python -I eval/train/evaluate_circuit_outputs.py --store-baseline hsd \
  --command-json '["python", "baseline/hsd_circuit.py", "--instance", "{instance}", "--output", "{output}"]'
python -I eval/train/evaluate_circuit_outputs.py --store-baseline bugassist_vote \
  --command-json '["python", "baseline/bugassist_vote_circuit.py", "--instance", "{instance}", "--output", "{output}"]'
bash scripts/evaluate_train.sh
