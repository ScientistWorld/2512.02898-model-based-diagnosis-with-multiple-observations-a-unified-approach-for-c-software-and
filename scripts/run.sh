#!/bin/bash
# End-to-end job (hardening iteration 11).  Builds (or reuses) the hidden
# ISCAS85 test and the fixed per-instance budget, stores the evaluator-owned
# baselines when missing, runs the reference through the train split and the
# hidden test, then runs every audit case (better/weaker variants, brute
# force, shortcuts, and the closed shortcuts against the previous evaluator)
# through the real scripts/evaluate_test.sh and summarises (HARDENING.md).
# Every phase is resumable (markers in tmp/, finished cases are skipped): the
# job may be preempted and restarted from the top.
#
# For a plain end-to-end reproduction of the reference only, use
# scripts/reproduce.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
chmod u+rwx eval/test 2>/dev/null || true   # an interrupted hidden test leaves it at mode 0
mkdir -p tmp logs

echo "== python / pysat"; python --version; python -c "import pysat; print('pysat', pysat.__version__)"
echo "== nproc $(nproc)"; date

echo "== smoke"; python redteam/hardening/smoke.py

echo "== build hidden benchmark + train split (reused when present)"; python eval/test/build_hidden_benchmark.py build
echo "== calibrate (fixed once)"; python eval/test/build_hidden_benchmark.py calibrate
echo "== budget (fixed once)"; python eval/test/build_hidden_benchmark.py limit
cat eval/train/config.json
echo "== baselines (stored once, evaluator-owned)"; python eval/test/build_hidden_benchmark.py baselines
date

echo "== reference: register + train + hidden test (final evaluator)"
rm -rf checkpoints/bugassist_vote checkpoints/hsd_circuit checkpoints/cfaults_circuit/results.json
python method/cfaults_circuit.py --register
if [ ! -f tmp/reference_train_done ]; then
  bash scripts/evaluate_train.sh > logs/reference_train.log 2>&1
  cp scoring/scores_train.json scoring/scores.json
  touch tmp/reference_train_done
fi
if [ ! -f tmp/reference_done ]; then
  bash scripts/evaluate_test.sh > logs/reference_test.log 2>&1
  touch tmp/reference_done
fi
date

echo "== audit cases"; python redteam/hardening/harness.py all
date
echo "== summary"; python redteam/hardening/summarize.py | tee redteam/hardening/summary.txt
echo "== validate"; python validate.py || true
date
