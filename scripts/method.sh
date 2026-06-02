#!/bin/bash
# Run the paper's proposed method.
#
# This script trains/runs the paper's method using code in method/.
#
# Usage:
#   bash scripts/method.sh

set -e

cd /home/user

python data/circuit_benchmark.py --out data/synthetic_circuits --instances-per-setting 3
python method/cfaults_circuit.py \
  --benchmark data/synthetic_circuits \
  --out checkpoints/cfaults_circuit/results.json \
  --solver auto
bash scripts/evaluate.sh
