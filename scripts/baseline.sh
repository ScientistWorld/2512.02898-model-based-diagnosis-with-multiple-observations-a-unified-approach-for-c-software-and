#!/bin/bash
# Run a baseline method from the paper.
#
# Baselines are simple reference methods the paper compares against. 
# Implement this only if applicable, i.e. the paper has baselines.
# You do not need to implement all baselines to begin — 
# just enough to validate that the evaluation pipeline works 
# and provide a reference point. You can decide to expand more baselines later.
# Each baseline must be actually run and scored through evaluate.sh
# so the numbers are verified, not self-reported.
# You can decide what this baseline script should do yourself.
#
# Usage:
#   bash scripts/baseline.sh <name>

set -e

cd /home/user

python data/circuit_benchmark.py --out data/synthetic_circuits --instances-per-setting 3
python baseline/bugassist_vote_circuit.py \
  --benchmark data/synthetic_circuits \
  --out checkpoints/bugassist_vote/results.json \
  --solver auto
bash scripts/evaluate.sh
