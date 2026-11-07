#!/usr/bin/env python3
"""Run end-to-end integrity, provenance, split, and manifest validations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_derived import hash_outputs
DATABASE = ROOT / "data/processed/vehicle_gpt.sqlite"
RAW_MANIFEST = ROOT / "data/manifests/raw_files.json"
INGESTION_REPORT = ROOT / "data/manifests/ingestion_report.json"
GROUND_TRUTH_DB = ROOT / "data/processed/ground_truth/ground_truth.sqlite"
GROUND_TRUTH_JSON = ROOT / "data/processed/ground_truth/injections.json"
SPLITS_CONFIG = ROOT / "configs/splits.yaml"
REPORT = ROOT / "data/manifests/validation_report.json"
DERIVED_HASHES = ROOT / "data/manifests/derived_output_hashes.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate() -> dict[str, object]:
    import yaml

    raw = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    ingestion = json.loads(INGESTION_REPORT.read_text(encoding="utf-8"))
    log = json.loads(GROUND_TRUTH_JSON.read_text(encoding="utf-8"))
    splits = yaml.safe_load(SPLITS_CONFIG.read_text(encoding="utf-8"))
    if not DATABASE.exists() or not GROUND_TRUTH_DB.exists():
        raise FileNotFoundError("canonical or ground-truth database is missing")

    raw_errors = []
    for item in raw["files"]:
        path = ROOT / item["path"]
        if not path.is_file():
            raw_errors.append(f"missing:{item['path']}")
            continue
        if path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
            raw_errors.append(f"changed:{item['path']}")

    main = sqlite3.connect(DATABASE)
    main.execute("PRAGMA foreign_keys=ON")
    gt = sqlite3.connect(GROUND_TRUTH_DB)
    gt.execute("PRAGMA foreign_keys=ON")
    try:
        integrity = main.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity_check failed: {integrity}")
        fk_main = main.execute("PRAGMA foreign_key_check").fetchall()
        fk_gt = gt.execute("PRAGMA foreign_key_check").fetchall()
        if fk_main or fk_gt:
            raise ValueError(f"foreign-key violations: main={len(fk_main)}, ground_truth={len(fk_gt)}")

        canonical_rows = main.execute("SELECT COUNT(*) FROM canonical_measurement").fetchone()[0]
        if canonical_rows != ingestion["canonical_rows"]:
            raise ValueError(f"canonical count mismatch: {canonical_rows} vs ingestion report")
        if main.execute("SELECT COUNT(*) FROM canonical_measurement WHERE provenance<>'real'").fetchone()[0]:
            raise ValueError("canonical layer contains non-real provenance")
        if main.execute(
            """SELECT COUNT(*) FROM canonical_measurement m JOIN signal_catalog s USING(signal)
               WHERE m.unit<>s.canonical_unit"""
        ).fetchone()[0]:
            raise ValueError("canonical unit differs from signal catalogue")
        if main.execute(
            """SELECT COUNT(*) FROM canonical_measurement m LEFT JOIN signal_catalog s USING(signal)
               WHERE s.signal IS NULL OR m.source_row<1 OR m.source_unit IS NULL"""
        ).fetchone()[0]:
            raise ValueError("canonical mapping/source traceability is incomplete")

        main_tables = {r[0] for r in main.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {"injection", "injection_signal", "split_manifest"} & main_tables:
            raise ValueError("ground-truth table leaked into the main database")
        gt_ids = {r[0] for r in gt.execute("SELECT injection_id FROM injection")}
        log_records = {r["injection_id"]: r for r in log["injections"]}
        if gt_ids != set(log_records):
            raise ValueError("ground-truth SQLite and JSON injection IDs differ")
        synthetic_events = main.execute(
            "SELECT event_id,injection_id FROM overlay_event WHERE provenance='synthetic'"
        ).fetchall()
        for event_id, injection_id in synthetic_events:
            if injection_id not in gt_ids or event_id not in log_records[injection_id]["overlay_event_ids"]:
                raise ValueError(f"synthetic event lacks ground-truth trace: {event_id}")
        signal_gt = {
            (r[0], r[1], r[2])
            for r in gt.execute("SELECT injection_id,signal,ts_replay_ns FROM injection_signal")
        }
        for injection_id, signal, stamp in main.execute(
            """SELECT os.injection_id,os.signal,os.ts_replay_ns FROM overlay_sample os
               WHERE os.provenance='synthetic'"""
        ):
            if (injection_id, signal, stamp) not in signal_gt:
                raise ValueError(f"synthetic sample lacks ground-truth trace: {injection_id}/{signal}/{stamp}")

        train = set(splits["train_development"])
        test = set(splits["held_out_test"])
        if train & test or train | test != gt_ids:
            raise ValueError("held-out split is overlapping or incomplete")
        sidecar_splits = dict(gt.execute("SELECT injection_id,split FROM injection"))
        if any(sidecar_splits.get(i) != "train_development" for i in train):
            raise ValueError("development split mismatch in ground-truth sidecar")
        if any(sidecar_splits.get(i) != "held_out_test" for i in test):
            raise ValueError("test split mismatch in ground-truth sidecar")

        derived = {
            table: main.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("derived_1hz", "trip_rollup", "event_window", "deviation_flag")
        }
        current_hashes = hash_outputs(main)
        recorded_hashes = json.loads(DERIVED_HASHES.read_text(encoding="utf-8"))
        if current_hashes != recorded_hashes:
            raise ValueError("derived output hashes differ from the recorded rebuild")
        if main.execute("SELECT COUNT(*) FROM derived_1hz WHERE interpolated<>0").fetchone()[0]:
            raise ValueError("unmarked/unsupported interpolation found in derived data")
        if main.execute("SELECT COUNT(*) FROM event_window WHERE offset_seconds NOT BETWEEN -60 AND 60").fetchone()[0]:
            raise ValueError("event window exceeds ±60 seconds")
        if main.execute(
            """SELECT COUNT(*) FROM vehicle_capability WHERE missing_rate NOT BETWEEN 0 AND 1
               OR (coverage IS NOT NULL AND coverage NOT BETWEEN 0 AND 1)"""
        ).fetchone()[0]:
            raise ValueError("capability rates fall outside [0,1]")
        if main.execute(
            """SELECT COUNT(*) FROM signal_coverage WHERE missing_count>sample_count
               OR (coverage IS NOT NULL AND coverage NOT BETWEEN 0 AND 1)"""
        ).fetchone()[0]:
            raise ValueError("signal coverage counts/rates are invalid")
        manifest_rows = main.execute("SELECT COUNT(*) FROM dataset_manifest").fetchone()[0]
        if manifest_rows != raw["file_count"] or manifest_rows != len(raw["files"]):
            raise ValueError("raw checksum manifest count mismatch")
        manifest_classification = dict(main.execute(
            "SELECT source_dataset,COUNT(*) FROM dataset_manifest GROUP BY source_dataset"
        ))
        expected_classification = {
            "ved": 6, "tum_bmw_i3": 72, "tum_simulation": 48,
            "comma2k19": 61, "openlka": 827,
        }
        if manifest_classification != expected_classification:
            raise ValueError(f"raw manifest source classification mismatch: {manifest_classification}")
        if raw_errors:
            raise ValueError(f"raw checksum mismatches: {len(raw_errors)}; first={raw_errors[0]}")

        result = {
            "status": "passed", "canonical_rows": canonical_rows,
            "raw_manifest_entries": manifest_rows,
            "synthetic_overlay_events": len(synthetic_events),
            "synthetic_overlay_samples": main.execute("SELECT COUNT(*) FROM overlay_sample").fetchone()[0],
            "ground_truth_injections": len(gt_ids), "train_development": len(train),
            "held_out_test": len(test), "derived_rows": derived,
            "derived_hashes_match": True,
            "sqlite_integrity": integrity, "foreign_key_violations": 0,
            "raw_checksums_verified": len(raw["files"]),
            "raw_files_by_source": manifest_classification,
        }
    finally:
        main.close()
        gt.close()
    REPORT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(validate(), sort_keys=True))
