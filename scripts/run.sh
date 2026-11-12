#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash redteam/nonminimal_padding_shortcut/run.sh
python redteam/summarize.py
