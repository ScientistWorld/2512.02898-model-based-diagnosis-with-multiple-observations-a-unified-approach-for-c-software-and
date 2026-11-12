#!/bin/bash
# Public train split.  Run with NO arguments.
#
# Same protocol as the hidden test, on the public instances in
# data/iscas85_train/: every method registered on disk
# (checkpoints/<name>/solver.json) is run on each instance under the same
# per-instance CPU budget and scored against the exact answers in
# data/iscas85_train/ground_truth.json.  Writes scoring/scores_train.json.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p scoring

python -I eval/train/evaluate_circuit_outputs.py --out scoring/scores_train.json
