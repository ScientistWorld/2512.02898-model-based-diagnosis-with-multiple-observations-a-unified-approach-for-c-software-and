#!/bin/bash
# Hardening job (iteration 11): build the hidden ISCAS85 test, choose the
# per-instance budget from train data, store evaluator-owned baselines, run
# the reference through train + hidden test, then run every audit case
# (better/weaker variants, brute force, shortcuts) through the real
# scripts/evaluate_test.sh and summarise.  Every phase is resumable.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
chmod u+rwx eval/test 2>/dev/null || true
mkdir -p tmp logs

echo "== python / pysat"; python --version; python -c "import pysat; print('pysat', pysat.__version__)"
echo "== nproc $(nproc)"; date

# Earlier audits are archived as evidence: results_base_only (job 1: HSD and simple
# exact variants at the bound), results_stress_v1 (job 2: 22-instance stress tier,
# previous fresh-solver reference).  This run: paper-faithful incremental reference
# and the larger stress tier v2.
if [ -d redteam/hardening/results ] && [ ! -d redteam/hardening/results_stress_v1 ]; then
  mv redteam/hardening/results redteam/hardening/results_stress_v1
  mv redteam/hardening/summary.json redteam/hardening/results_stress_v1/summary.json || true
  mv redteam/hardening/summary.txt redteam/hardening/results_stress_v1/summary.txt || true
  cp scoring/scores_test.json redteam/hardening/results_stress_v1/reference_scores_test.json || true
  cp scoring/scores_train.json redteam/hardening/results_stress_v1/reference_scores_train.json || true
  rm -rf eval/test/baseline_outputs eval/train/baseline_outputs tmp/reference_done
fi

echo "== smoke"; python redteam/hardening/smoke.py

echo "== build hidden benchmark + train split"; python eval/test/build_hidden_benchmark.py build
echo "== calibrate"; python eval/test/build_hidden_benchmark.py calibrate
echo "== choose budget from train"; python eval/test/build_hidden_benchmark.py limit
cat eval/test/config.json
echo "== baselines"; python eval/test/build_hidden_benchmark.py baselines
date

echo "== reference: register + train + hidden test"
rm -rf checkpoints/bugassist_vote checkpoints/hsd_circuit checkpoints/cfaults_circuit/results.json
python method/cfaults_circuit.py --register
if [ ! -f tmp/reference_done ]; then
  bash scripts/evaluate_train.sh > logs/reference_train.log 2>&1
  cp scoring/scores_train.json scoring/scores.json
  bash scripts/evaluate_test.sh > logs/reference_test.log 2>&1
  touch tmp/reference_done
fi
date

echo "== audit cases"; python redteam/hardening/harness.py all
date
echo "== summary"; python redteam/hardening/summarize.py | tee redteam/hardening/summary.txt
echo "== validate"; python validate.py || true
date
