#!/bin/bash
# Standard evaluation entry point (public train split).
#
# Self-contained: uses only eval/ code and never imports method/.  Every
# method registered under checkpoints/<name>/solver.json is run on the public
# training instances under the fixed per-instance instruction budget and scored.
# Writes scoring/scores.json (same content and format as scores_train.json).
#
# Usage:
#   bash scripts/evaluate.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p scoring

python -I eval/train/evaluate_circuit_outputs.py --out scoring/scores.json
