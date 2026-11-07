#!/usr/bin/env python3
"""Build the canonical VehicleGPT database from supplied local sources."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.ingest.comma2k19 import load_comma2k19, verify_segment
from vehicle_gpt.ingest.openlka import load_openlka
from vehicle_gpt.ingest.tum import load_tum
from vehicle_gpt.ingest.ved import load_ved
from vehicle_gpt.storage.database import initialize_database, load_catalogue


DEFAULT_DATABASE = ROOT / "data/processed/vehicle_gpt.sqlite"
RAW_MANIFEST = ROOT / "data/manifests/raw_files.json"
REPORT = ROOT / "data/manifests/ingestion_report.json"


def _dataset_name(path: str) -> str:
    parts = Path(path).parts
    if len(parts) >= 2 and parts[0] == "DATASET" and parts[1] == "VED-master":
        return "ved"
    if len(parts) >= 2 and parts[:2] == ("DATASET", "Measurement Data"):
        return "tum_bmw_i3"
    if len(parts) >= 2 and parts[:2] == ("DATASET", "Simulation Data"):
        return "tum_simulation"
    if len(parts) >= 2 and parts[0] == "DATASET" and parts[1] == "comma2k19-master":
        return "comma2k19"
    if len(parts) >= 2 and parts[0] == "DATASET" and parts[1] == "OpenLKA-main":
        return "openlka"
    return "project_reference"


def _load_raw_manifest(connection: sqlite3.Connection) -> int:
    manifest = json.loads(RAW_MANIFEST.read_text(encoding="utf-8"))
    records = [
        (
            _dataset_name(item["path"]),
            item["path"],
            item["bytes"],
            item["sha256"],
            1,
        )
        for item in manifest["files"]
    ]
    connection.executemany(
        """INSERT INTO dataset_manifest(source_dataset,source_path,size_bytes,sha256,immutable)
           VALUES (?,?,?,?,?) ON CONFLICT(source_dataset,source_path) DO UPDATE SET
           size_bytes=excluded.size_bytes,sha256=excluded.sha256,immutable=excluded.immutable""",
        records,
    )
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="remove the existing generated database before rebuilding it",
    )
    parser.add_argument(
        "--resume-comma",
        action="store_true",
        help="finish comma2k19 ingestion in an existing VED/TUM/OpenLKA build",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    if args.resume_comma and not database.exists():
        parser.error(f"cannot resume; database does not exist: {database}")
    if args.resume_comma and args.replace:
        parser.error("--resume-comma cannot be combined with --replace")
    if database.exists() and not args.replace:
        if not args.resume_comma:
            parser.error(f"database exists; choose another path or pass --replace: {database}")
    if args.replace:
        for suffix in ("", "-wal", "-shm"):
            Path(str(database) + suffix).unlink(missing_ok=True)

    catalogue = load_catalogue()
    connection = initialize_database(database, catalogue)
    try:
        segment = ROOT / "DATASET/comma2k19-master/Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40"
        can_validation = verify_segment(segment)
        if args.resume_comma:
            manifest_count = connection.execute(
                "SELECT COUNT(*) FROM dataset_manifest"
            ).fetchone()[0]
            reports = [load_comma2k19(connection, catalogue, segment, ROOT)]
        else:
            manifest_count = _load_raw_manifest(connection)
            reports = [
                load_ved(connection, catalogue, ROOT / "DATASET/VED-master"),
                load_tum(connection, catalogue, ROOT),
                load_openlka(
                    connection,
                    catalogue,
                    ROOT / "DATASET/OpenLKA-main/OpenLKA-Failure-Sample",
                ),
                load_comma2k19(connection, catalogue, segment, ROOT),
            ]
        connection.commit()
        source_counts = dict(connection.execute(
            "SELECT source_dataset,COUNT(*) FROM canonical_measurement GROUP BY source_dataset"
        ))
        if args.resume_comma:
            reports = [
                {"dataset": name, "canonical_rows": count}
                for name, count in sorted(source_counts.items())
            ]
        summary = {
            "database": database.relative_to(ROOT).as_posix()
            if database.is_relative_to(ROOT)
            else str(database),
            "raw_manifest_entries": manifest_count,
            "datasets": reports,
            "can_mapping_validation": can_validation,
            "canonical_rows": sum(int(report["canonical_rows"]) for report in reports),
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
