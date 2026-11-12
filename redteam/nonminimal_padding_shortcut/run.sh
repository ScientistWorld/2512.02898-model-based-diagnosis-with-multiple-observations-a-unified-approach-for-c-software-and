#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python redteam/harness.py nonminimal_padding_shortcut
