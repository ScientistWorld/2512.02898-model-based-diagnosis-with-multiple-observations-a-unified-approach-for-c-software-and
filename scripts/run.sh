#!/bin/bash
# Hardening job (iteration 11, part 2).  Builds (or reuses) the hidden ISCAS85
# test, regenerates the evaluator-owned baselines and the reference with the FINAL evaluators
# (process-tree CPU accounting, tamper detection), then runs every audit case
# (better/weaker variants, brute force, shortcuts, and the newly closed
# shortcuts against the previous evaluator) through the real
# scripts/evaluate_test.sh and summarises.  Every phase is resumable: the job
# may be preempted and restarted from the top.
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

# One-time reset for part 2: the previous audit (job d3e44907, previous
# evaluator) is archived as evidence; baselines and the reference are rerun
# with the final evaluator.
if [ ! -f tmp/hardening_v4_init ]; then
  if [ -d redteam/hardening/results ] && [ ! -d redteam/hardening/results_v3_prefix ]; then
    mv redteam/hardening/results redteam/hardening/results_v3_prefix
    mv redteam/hardening/summary.json redteam/hardening/results_v3_prefix/summary.json || true
    mv redteam/hardening/summary.txt redteam/hardening/results_v3_prefix/summary.txt || true
    cp scoring/scores_test.json redteam/hardening/results_v3_prefix/reference_scores_test.json || true
    cp scoring/scores_train.json redteam/hardening/results_v3_prefix/reference_scores_train.json || true
  fi
  rm -rf eval/test/baseline_outputs eval/train/baseline_outputs tmp/reference_done tmp/reference_train_done
  touch tmp/hardening_v4_init
fi
# Part 2b: the train calibration reference was restored to its build-time value
# (see eval/train/config.json "alignment_check"): rerun the train side only.
if [ ! -f tmp/hardening_v5_train_init ]; then
  rm -rf eval/train/baseline_outputs tmp/reference_train_done
  touch tmp/hardening_v5_train_init
fi

echo "== smoke"; python redteam/hardening/smoke.py

echo "== build hidden benchmark + train split (reused when present)"; python eval/test/build_hidden_benchmark.py build
echo "== calibrate (fixed once)"; python eval/test/build_hidden_benchmark.py calibrate
echo "== budget (fixed once)"; python eval/test/build_hidden_benchmark.py limit
cat eval/train/config.json
echo "== baselines (final evaluator)"; python eval/test/build_hidden_benchmark.py baselines
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
