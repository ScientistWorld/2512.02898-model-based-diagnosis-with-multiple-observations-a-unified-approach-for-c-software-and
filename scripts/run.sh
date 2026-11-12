#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash redteam/run_all.sh
