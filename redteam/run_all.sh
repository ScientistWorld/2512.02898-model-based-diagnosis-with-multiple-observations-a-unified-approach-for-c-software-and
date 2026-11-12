#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python redteam/harness.py all
python redteam/summarize.py
python redteam/check_evidence.py
