#!/usr/bin/env python3
"""Read-only inspector for the operational VehicleGPT SQLite database."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
MAIN_DB = ROOT / "data/processed/vehicle_gpt.sqlite"
GT_DB = ROOT / "data/processed/ground_truth/ground_truth.sqlite"


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _limit(value: int) -> int:
    if value < 1 or value > 100_000:
        raise ValueError("--limit must be between 1 and 100000")
    return value


def _vehicles(connection):
    return [dict(r) for r in connection.execute(
        """SELECT v.vehicle_id,v.source_dataset,v.make,v.model,v.model_year,v.powertrain,
                  COUNT(t.trip_id) AS trip_count,MIN(t.ts_replay_start) AS first_time,
                  MAX(t.ts_replay_end) AS last_time
           FROM vehicle_registry v LEFT JOIN trip_registry t USING(vehicle_id)
           GROUP BY v.vehicle_id ORDER BY v.vehicle_id"""
    )]


def _signals(connection, vehicle_id):
    return [dict(r) for r in connection.execute(
        """SELECT c.signal,c.unit,c.source_dataset,c.expected_sampling_hz,
                  c.observed_sampling_hz,c.sample_count,c.missing_rate,c.coverage,
                  c.provenance,s.description
           FROM vehicle_capability c JOIN signal_catalog s USING(signal)
           WHERE c.vehicle_id=? ORDER BY c.signal""",
        (vehicle_id,),
    )]


def _ensure_signal(connection, vehicle_id, signal):
    row = connection.execute(
        "SELECT 1 FROM vehicle_capability WHERE vehicle_id=? AND signal=?",
        (vehicle_id, signal),
    ).fetchone()
    if row is None:
        raise ValueError(f"signal {signal!r} is unavailable for vehicle {vehicle_id!r}")


def _sample_query(connection, vehicle, signal, limit):
    _ensure_signal(connection, vehicle, signal)
    has_replay = connection.execute(
        "SELECT 1 FROM canonical_measurement WHERE vehicle_id=? AND signal=? AND ts_replay_ns IS NOT NULL LIMIT 1",
        (vehicle, signal),
    ).fetchone()
    order = "ts_replay_ns,trip_id,measurement_id" if has_replay else "ts_source_seconds,trip_id,measurement_id"
    return [dict(r) for r in connection.execute(
        f"""SELECT trip_id,signal,unit,ts_source,ts_source_seconds,ts_replay,
                   value,quality_flag,provenance,source_dataset,source_file,source_row
            FROM canonical_measurement WHERE vehicle_id=? AND signal=?
            ORDER BY {order} LIMIT ?""",
        (vehicle, signal, limit),
    )]


def run(args) -> int:
    if args.command == "evaluation-injections":
        if not args.evaluation_only:
            raise ValueError("evaluation-injections requires explicit --evaluation-only")
        connection = connect_readonly(GT_DB)
        try:
            rows = [dict(r) for r in connection.execute(
                """SELECT injection_id,vehicle_id,trip_id,event_type,ts_replay_ns,
                          expected_label,split,created_by_version
                   FROM injection ORDER BY ts_replay_ns,injection_id LIMIT ?""",
                (_limit(args.limit),),
            )]
            _print(rows)
        finally:
            connection.close()
        return 0

    connection = connect_readonly(args.database)
    try:
        if args.command == "summary":
            tables = [r[0] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            summary = {
                "database": str(args.database),
                "vehicles": connection.execute("SELECT COUNT(*) FROM vehicle_registry").fetchone()[0],
                "trips": connection.execute("SELECT COUNT(*) FROM trip_registry").fetchone()[0],
                "canonical_measurements": connection.execute("SELECT COUNT(*) FROM canonical_measurement").fetchone()[0],
                "overlay_events": connection.execute("SELECT COUNT(*) FROM overlay_event").fetchone()[0],
                "overlay_samples": connection.execute("SELECT COUNT(*) FROM overlay_sample").fetchone()[0],
                "tables": sorted(tables),
            }
            _print(summary)
        elif args.command == "vehicles":
            _print(_vehicles(connection))
        elif args.command == "vehicle":
            row = connection.execute("SELECT * FROM vehicle_registry WHERE vehicle_id=?", (args.id,)).fetchone()
            if row is None:
                raise ValueError(f"unknown vehicle: {args.id}")
            result = dict(row)
            result["trips"] = [dict(r) for r in connection.execute(
                "SELECT trip_id,source_trip_key,ts_replay_start,ts_replay_end,timestamp_basis,provenance FROM trip_registry WHERE vehicle_id=? ORDER BY ts_replay_start,trip_id",
                (args.id,),
            )]
            result["available_signal_count"] = connection.execute(
                "SELECT COUNT(*) FROM vehicle_capability WHERE vehicle_id=?", (args.id,)
            ).fetchone()[0]
            _print(result)
        elif args.command == "trips":
            rows = [dict(r) for r in connection.execute(
                """SELECT trip_id,source_dataset,ts_source_start,ts_source_end,
                          ts_replay_start,ts_replay_end,timestamp_basis,provenance
                   FROM trip_registry WHERE vehicle_id=? ORDER BY ts_replay_start,trip_id""",
                (args.vehicle,),
            )]
            if not rows:
                raise ValueError(f"no trips found for vehicle {args.vehicle!r}")
            _print(rows)
        elif args.command == "signals":
            _print(_signals(connection, args.vehicle))
        elif args.command == "signal":
            _ensure_signal(connection, args.vehicle, args.name)
            _print([r for r in _signals(connection, args.vehicle) if r["signal"] == args.name])
            rows = connection.execute(
                """SELECT COUNT(*) AS rows,MIN(ts_replay) AS first_time,MAX(ts_replay) AS last_time,
                          MIN(value) AS min_value,MAX(value) AS max_value,
                          SUM(value IS NULL) AS missing
                   FROM canonical_measurement WHERE vehicle_id=? AND signal=?""",
                (args.vehicle, args.name),
            ).fetchone()
            _print({"signal_detail": dict(rows)})
        elif args.command == "provenance":
            output = {}
            for table in ("canonical_measurement", "overlay_event", "overlay_sample", "derived_1hz"):
                output[table] = [dict(r) for r in connection.execute(
                    f"SELECT provenance,COUNT(*) AS rows FROM {table} GROUP BY provenance ORDER BY provenance"
                )]
            _print(output)
        elif args.command == "quality":
            _print([dict(r) for r in connection.execute(
                """SELECT source_dataset,quality_flag,COUNT(*) AS rows,
                          SUM(value IS NULL) AS missing_values
                   FROM canonical_measurement GROUP BY source_dataset,quality_flag
                   ORDER BY source_dataset,quality_flag"""
            )])
        elif args.command == "events":
            _print([dict(r) for r in connection.execute(
                """SELECT event_id,vehicle_id,trip_id,event_type,ts_replay,provenance,
                          injection_id,event_metadata_json
                   FROM overlay_event ORDER BY ts_replay_ns,event_id LIMIT ?""",
                (_limit(args.limit),),
            )])
        elif args.command == "schema":
            tables = [r[0] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            schema = {}
            for table in tables:
                schema[table] = {
                    "columns": [dict(r) for r in connection.execute(f"PRAGMA table_info('{table}')")],
                    "foreign_keys": [dict(r) for r in connection.execute(f"PRAGMA foreign_key_list('{table}')")],
                }
            _print(schema)
        elif args.command == "sample":
            _print(_sample_query(connection, args.vehicle, args.signal, _limit(args.limit)))
        elif args.command == "export":
            rows = _sample_query(connection, args.vehicle, args.signal, _limit(args.limit))
            if not rows:
                raise ValueError("no canonical rows matched the requested vehicle and signal")
            with args.output.open("w", encoding="utf-8", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            print(f"exported={len(rows)} output={args.output}")
        else:
            raise ValueError(f"unsupported command {args.command!r}")
    finally:
        connection.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=MAIN_DB, help="operational database path")
    parser.add_argument("--evaluation-only", action="store_true", help="explicitly permit the evaluation-only command")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("summary")
    sub.add_parser("vehicles")
    vehicle = sub.add_parser("vehicle"); vehicle.add_argument("--id", required=True)
    trips = sub.add_parser("trips"); trips.add_argument("--vehicle", required=True)
    signals = sub.add_parser("signals"); signals.add_argument("--vehicle", required=True)
    signal = sub.add_parser("signal"); signal.add_argument("--vehicle", required=True); signal.add_argument("--name", required=True)
    sub.add_parser("provenance")
    sub.add_parser("quality")
    events = sub.add_parser("events"); events.add_argument("--limit", type=int, default=100)
    sub.add_parser("schema")
    sample = sub.add_parser("sample"); sample.add_argument("--vehicle", required=True); sample.add_argument("--signal", required=True); sample.add_argument("--limit", type=int, default=20)
    export = sub.add_parser("export"); export.add_argument("--vehicle", required=True); export.add_argument("--signal", required=True); export.add_argument("--output", type=Path, required=True); export.add_argument("--limit", type=int, default=1000)
    evaluation = sub.add_parser("evaluation-injections"); evaluation.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, sqlite3.Error, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
