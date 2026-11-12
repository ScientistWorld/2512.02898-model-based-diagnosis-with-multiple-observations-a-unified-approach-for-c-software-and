#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python redteam/harness.py negative_work_shortcut
