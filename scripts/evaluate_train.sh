#!/bin/bash
# Evaluate the visible train slice of the circuit benchmark.
#
# Contract mirrors scripts/evaluate.sh: callable standalone after methods have
# written result artifacts. Positional $1 is accepted for compatibility with the
# legacy method/run-name shape; methods are enumerated from RESULT_ROOT.

set -e

cd /home/user

mkdir -p scoring

BENCHMARK="${EVAL_BENCHMARK:-data/synthetic_circuits}"
RESULT_ROOT="${EVAL_RESULT_ROOT:-${2:-checkpoints}}"
OUT="${EVAL_TRAIN_OUT:-scoring/scores_train.json}"

python eval/train/evaluate_circuit_outputs.py \
  --benchmark "$BENCHMARK" \
  --result-root "$RESULT_ROOT" \
  --out "$OUT"
