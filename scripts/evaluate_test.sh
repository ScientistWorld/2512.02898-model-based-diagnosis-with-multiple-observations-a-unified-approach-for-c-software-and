#!/bin/bash
# Hidden test.  Run with NO arguments.
#
# Runs every method registered on disk (checkpoints/<name>/solver.json, see
# briefing/evaluation.md) on the hidden ISCAS85-derived test instances held in
# eval/test/, one fresh process per instance under a fixed per-instance work
# budget (user-space instructions retired by the method's whole process tree,
# counted by the evaluator), and scores the raw diagnoses each method wrote
# against the exact answers.  Evaluator-owned baselines (hsd, bugassist_vote) are scored from
# their stored outputs.  Writes scoring/scores_test.json.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
mkdir -p scoring

python -I eval/test/evaluate_circuit_outputs.py --out scoring/scores_test.json
