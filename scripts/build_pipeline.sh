#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

scripts/run_limited.sh python3 scripts/build_dataset.py --replace
scripts/run_limited.sh python3 scripts/build_capabilities.py
scripts/run_limited.sh python3 scripts/generate_overlays.py
scripts/run_limited.sh python3 scripts/build_derived.py
