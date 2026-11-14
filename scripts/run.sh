#!/bin/bash
# End-to-end job (hardening iteration 12).
#
#   1. smoke checks (hardware instruction counter in this container, solver
#      agreement with the exact enumerator, runner end to end)
#   2. build the public train split and the hidden test split with exact
#      answers (resumable, parallel over cells)
#   3. choose the per-instance instruction budget from the reference on the
#      public train split (runs while the hidden split builds)
#   4. in parallel:
#        A. hidden test: evaluator-owned baselines (HSD, BugAssist voting),
#           then the official reference run (scripts/evaluate_test.sh)
#        B. train: baselines and the reference (scores_train.json)
#        C. audit cases (variants, brute force, shortcuts), each through
#           scripts/evaluate_test.sh with no arguments in its own workspace
#   5. summary (HARDENING.md) and validate.py
#
# Every phase is resumable (markers in tmp/, finished cases are skipped): the
# job may be preempted and restarted from the top.  For a plain reproduction
# of the reference only, use scripts/reproduce.sh.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
chmod u+rwx eval/test 2>/dev/null || true   # an interrupted hidden test leaves it at mode 0
mkdir -p tmp logs

echo "== python / pysat"; python --version; python -c "import pysat; print('pysat', pysat.__version__)"
echo "== nproc $(nproc)"; date
cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null || true
cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true
grep -E "MemTotal|MemAvailable" /proc/meminfo || true

# concurrency: cores, and about 2.5 GB per concurrent solver process
PAR=$(python - <<'EOF'
import os
n = os.cpu_count() or 1
mem = None
for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
    try:
        v = open(path).read().strip()
        if v.isdigit():
            mem = int(v)
            break
    except OSError:
        pass
try:
    avail = int([l for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0].split()[1]) * 1024
    mem = min(mem, avail) if mem else avail
except Exception:
    pass
print(n if mem is None else max(1, min(n, int(mem / 2.5e9))))
EOF
)
echo "== concurrency $PAR"

if [ ! -f tmp/smoke_done ]; then
  echo "== smoke"; python redteam/hardening/smoke.py 2>&1 | tee logs/smoke.log
  touch tmp/smoke_done
fi

echo "== build train split"; date
python eval/test/build_hidden_benchmark.py build --split train --workers "$PAR"
echo "== budget probe on train (background) + build hidden split"; date
python method/cfaults_circuit.py --register
( python eval/test/build_hidden_benchmark.py budget > logs/budget.log 2>&1 ) &
BUDGET_PID=$!
python eval/test/build_hidden_benchmark.py build --split test --workers "$(( PAR > 1 ? PAR - 1 : 1 ))"
wait "$BUDGET_PID" || { cat logs/budget.log; exit 1; }
tail -3 logs/budget.log
cat eval/test/config.json
date

echo "== snapshot for the audit cases"
rm -rf checkpoints/bugassist_vote checkpoints/hsd_circuit
if [ ! -f tmp/snapshot_done ]; then
  python redteam/hardening/harness.py snapshot
  touch tmp/snapshot_done
fi

echo "== parallel: hidden-test baselines + reference | train baselines + reference | audit cases"; date
(
  set -e
  python eval/test/build_hidden_benchmark.py baselines --split test > logs/baselines_test.log 2>&1
  if [ ! -f tmp/reference_test_done ]; then
    bash scripts/evaluate_test.sh > logs/reference_test.log 2>&1
    touch tmp/reference_test_done
  fi
) &
CHAIN_A=$!
(
  set -e
  for name in hsd bugassist_vote; do
    if [ ! -f "eval/train/baseline_outputs/$name.json.gz" ]; then
      script="baseline/hsd_circuit.py"; [ "$name" = bugassist_vote ] && script="baseline/bugassist_vote_circuit.py"
      python -I eval/train/evaluate_circuit_outputs.py --store-baseline "$name" \
        --command-json "[\"python\", \"$script\", \"--instance\", \"{instance}\", \"--output\", \"{output}\"]" \
        > "logs/baseline_${name}_train.log" 2>&1 &
    fi
  done
  if [ ! -f tmp/reference_train_done ]; then
    python -I eval/train/evaluate_circuit_outputs.py --methods cfaults --out tmp/reference_train_scores.json \
      > logs/reference_train.log 2>&1
  fi
  wait
  python -I eval/train/evaluate_circuit_outputs.py --rescore --out scoring/scores_train.json > logs/reference_train_rescore.log 2>&1
  cp scoring/scores_train.json scoring/scores.json
  touch tmp/reference_train_done
) &
CHAIN_B=$!
python redteam/hardening/harness.py "--jobs=$(( PAR > 3 ? PAR - 2 : 1 ))" all > logs/harness.log 2>&1 || true
wait "$CHAIN_A" || { echo "chain A (hidden-test baselines/reference) failed"; tail -20 logs/baselines_test.log logs/reference_test.log; }
wait "$CHAIN_B" || { echo "chain B (train) failed"; tail -20 logs/reference_train.log; }
date
tail -40 logs/harness.log || true

echo "== summary"; python redteam/hardening/summarize.py | tee redteam/hardening/summary.txt
echo "== validate"; python validate.py || true
date
