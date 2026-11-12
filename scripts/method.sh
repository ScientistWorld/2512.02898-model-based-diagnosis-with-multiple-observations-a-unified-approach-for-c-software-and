#!/bin/bash
# Register the paper's method (CFaults, unified multi-observation MaxSAT) and
# score it on the public train split.
#
# The method needs no training: "running" it means registering its command in
# checkpoints/cfaults_circuit/solver.json; the evaluators then run it on each
# instance themselves (train: scripts/evaluate_train.sh, hidden test:
# scripts/evaluate_test.sh).
#
# Usage:
#   bash scripts/method.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python method/cfaults_circuit.py --register
bash scripts/evaluate_train.sh
