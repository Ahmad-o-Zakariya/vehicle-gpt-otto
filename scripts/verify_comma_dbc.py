#!/usr/bin/env python3
"""Validate pinned Toyota DBC signal mappings against comma2k19 raw CAN."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.ingest.comma2k19 import verify_segment

SEGMENT = ROOT / "DATASET/comma2k19-master/Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40"
OUTPUT = ROOT / "data/manifests/comma_dbc_validation.json"


def main() -> int:
    report = verify_segment(SEGMENT)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
