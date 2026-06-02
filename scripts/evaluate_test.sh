#!/bin/bash
# Evaluate the held-out test slice of the circuit benchmark.
#
# Contract mirrors scripts/evaluate.sh: callable standalone after methods have
# written result artifacts. Positional $1 is the result root; methods are
# enumerated from RESULT_ROOT and, when scoring/scores_train.json exists,
# restricted to the exact method keys scored on the train slice.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p scoring

BENCHMARK="${EVAL_BENCHMARK:-data/synthetic_circuits}"
RESULT_ROOT="${EVAL_RESULT_ROOT:-${1:-checkpoints}}"
TRAIN_SCORES="${EVAL_TRAIN_SCORES:-scoring/scores_train.json}"
OUT="${EVAL_TEST_OUT:-scoring/scores_test.json}"

python eval/test/evaluate_circuit_outputs.py \
  --benchmark "$BENCHMARK" \
  --result-root "$RESULT_ROOT" \
  --train-scores "$TRAIN_SCORES" \
  --out "$OUT"
