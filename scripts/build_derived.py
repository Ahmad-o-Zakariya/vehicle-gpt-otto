#!/usr/bin/env python3
"""Rebuild the 1 Hz, rollup, event-window, and deviation layers deterministically."""

from __future__ import annotations

import json
import argparse
import hashlib
import math
import sqlite3
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vehicle_gpt.storage.database import initialize_database, load_catalogue

DATABASE = ROOT / "data/processed/vehicle_gpt.sqlite"
HASH_MANIFEST = ROOT / "data/manifests/derived_output_hashes.json"
PRECISION = 8
WINDOW_SECONDS = 60
MIN_BASELINE = 10
SIGMA_MULTIPLIER = 3.0


def _build_1hz(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM derived_1hz")
    sql = f"""
    WITH overlay_rows AS (
      SELECT oe.vehicle_id,oe.trip_id,os.signal,os.unit,os.ts_replay_ns AS t_ns,
             os.value,os.quality_flag,'synthetic' AS provenance
      FROM overlay_sample os JOIN overlay_event oe ON oe.event_id=os.event_id
    ), overlay_buckets AS (
      SELECT DISTINCT vehicle_id,trip_id,signal,
             (t_ns/1000000000)*1000000000 AS bucket_ns
      FROM overlay_rows WHERE t_ns IS NOT NULL
    ), effective AS (
      SELECT cm.vehicle_id,cm.trip_id,cm.signal,cm.unit,
             COALESCE(cm.ts_replay_ns,CAST(ROUND(cm.ts_source_seconds*1000000000.0) AS INTEGER)) AS t_ns,
             cm.value,cm.quality_flag,cm.provenance
      FROM canonical_measurement cm
      WHERE NOT EXISTS (
        SELECT 1 FROM overlay_buckets ob
        WHERE ob.vehicle_id=cm.vehicle_id AND ob.trip_id=cm.trip_id
          AND ob.signal=cm.signal
          AND ob.bucket_ns=(COALESCE(cm.ts_replay_ns,CAST(ROUND(cm.ts_source_seconds*1000000000.0) AS INTEGER))/1000000000)*1000000000
      )
      UNION ALL
      SELECT vehicle_id,trip_id,signal,unit,t_ns,value,quality_flag,provenance
      FROM overlay_rows
    ), bucketed AS (
      SELECT vehicle_id,trip_id,signal,unit,(t_ns/1000000000)*1000000000 AS bucket_ns,
             value,quality_flag,provenance
      FROM effective WHERE t_ns IS NOT NULL
    )
    INSERT INTO derived_1hz(vehicle_id,trip_id,signal,unit,bucket_start_ns,value,
      sample_count,aggregation_method,interpolated,quality_flag,provenance)
    SELECT vehicle_id,trip_id,signal,unit,bucket_ns,ROUND(AVG(value),{PRECISION}),
      COUNT(*),'mean_per_1s_bucket_no_interpolation',0,
      CASE WHEN SUM(CASE WHEN value IS NOT NULL THEN 1 ELSE 0 END)=0 THEN 'all_missing'
           WHEN SUM(CASE WHEN value IS NULL OR quality_flag NOT IN ('ok','synthetic_injected') THEN 1 ELSE 0 END)>0 THEN 'contains_missing_or_source_quality'
           ELSE 'ok' END,
      CASE WHEN SUM(CASE WHEN provenance='real' THEN 1 ELSE 0 END)>0
                 AND SUM(CASE WHEN provenance='synthetic' THEN 1 ELSE 0 END)>0 THEN 'real+overlay'
           WHEN SUM(CASE WHEN provenance='synthetic' THEN 1 ELSE 0 END)>0 THEN 'synthetic'
           ELSE 'real' END
    FROM bucketed GROUP BY vehicle_id,trip_id,signal,unit,bucket_ns
    """
    connection.executescript(sql)


def _build_rollups(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM trip_rollup")
    cursor = connection.execute(
        """SELECT vehicle_id,trip_id,signal,unit,bucket_start_ns,value,quality_flag
           FROM derived_1hz ORDER BY vehicle_id,trip_id,signal,bucket_start_ns"""
    )
    group_key = None
    state = None
    def finish(key, current):
        if key is None:
            return
        vehicle, trip, signal, unit = key
        values = current["values"]
        nonmissing = len(values)
        duration = max(0.0, (current["last_ns"] - current["first_ns"]) / 1e9)
        expected = duration + 1.0
        coverage = min(1.0, nonmissing / expected) if expected else None
        summaries = (
            ("mean", sum(values) / nonmissing if nonmissing else None),
            ("min", min(values) if nonmissing else None),
            ("max", max(values) if nonmissing else None),
            ("valid_buckets", float(nonmissing)),
            ("missing_buckets", float(current["rows"] - nonmissing)),
        )
        method = "1Hz means; no interpolation; overlay precedence applied"
        for metric, value in summaries:
            connection.execute(
                """INSERT INTO trip_rollup(vehicle_id,trip_id,metric,value,unit,coverage,method)
                   VALUES (?,?,?,?,?,?,?)""",
                (vehicle, trip, f"{signal}.{metric}", value,
                 unit if metric in ("mean", "min", "max") else "count",
                 coverage, method),
            )
        if signal == "vehicle.speed" and values:
            connection.execute(
                """INSERT INTO trip_rollup VALUES (?,?,?,?,?,?,?)""",
                (vehicle, trip, "distance_estimate", round(sum(values), PRECISION),
                 "m", coverage, "sum of 1 Hz mean speed (m/s); missing buckets omitted"),
            )

    for row in cursor:
        key = (row[0], row[1], row[2], row[3])
        if key != group_key:
            finish(group_key, state)
            group_key = key
            state = {"values": [], "rows": 0, "first_ns": row[4], "last_ns": row[4]}
        state["rows"] += 1
        state["last_ns"] = row[4]
        if row[5] is not None:
            state["values"].append(float(row[5]))
    finish(group_key, state)
    connection.execute(
        """INSERT INTO trip_rollup(vehicle_id,trip_id,metric,value,unit,coverage,method)
           SELECT vehicle_id,trip_id,'duration_seconds',
             (MAX(bucket_start_ns)-MIN(bucket_start_ns))/1000000000.0,'s',NULL,
             'span of searchable source-derived 1 Hz coordinates'
           FROM derived_1hz GROUP BY vehicle_id,trip_id"""
    )


def _build_event_windows(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM event_window")
    connection.execute(
        """INSERT INTO event_window(event_id,offset_seconds,signal,unit,value,quality_flag,provenance)
           SELECT e.event_id,
             CAST(ROUND((d.bucket_start_ns-e.ts_replay_ns)/1000000000.0) AS INTEGER),
             d.signal,d.unit,d.value,d.quality_flag,d.provenance
           FROM overlay_event e JOIN derived_1hz d
             ON d.vehicle_id=e.vehicle_id AND d.trip_id=e.trip_id
            AND d.bucket_start_ns BETWEEN e.ts_replay_ns-60000000000 AND e.ts_replay_ns+60000000000
           WHERE e.ts_replay_ns IS NOT NULL
             AND ABS(ROUND((d.bucket_start_ns-e.ts_replay_ns)/1000000000.0))<=60"""
    )


def _build_deviations(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM deviation_flag")
    cursor = connection.execute(
        """SELECT vehicle_id,trip_id,signal,bucket_start_ns,value,quality_flag,provenance
           FROM derived_1hz ORDER BY vehicle_id,trip_id,signal,bucket_start_ns"""
    )
    key = None
    history = deque(maxlen=60)
    last_ns = None
    for row in cursor:
        current_key = row[:3]
        if current_key != key:
            key = current_key
            history.clear()
            last_ns = None
        stamp = int(row[3])
        if last_ns is not None and stamp - last_ns > 2_000_000_000:
            history.clear()
        last_ns = stamp
        value = row[4]
        if value is None:
            continue
        value = float(value)
        if len(history) >= MIN_BASELINE:
            baseline = sum(history) / len(history)
            variance = sum((x - baseline) ** 2 for x in history) / len(history)
            stddev = math.sqrt(variance)
            floor = 0.5 if row[2].endswith("temperature") or "temperature" in row[2] else 0.1
            threshold = SIGMA_MULTIPLIER * max(stddev, floor)
            if abs(value - baseline) > threshold:
                connection.execute(
                    """INSERT INTO deviation_flag VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (row[0], row[1], row[2], stamp, round(value, PRECISION),
                     round(baseline, PRECISION), round(stddev, PRECISION), round(threshold, PRECISION),
                     "causal_trailing_60_valid_samples_3sigma", row[5], row[6]),
                )
        history.append(value)


def build(connection: sqlite3.Connection) -> dict[str, int]:
    connection.execute("CREATE INDEX IF NOT EXISTS idx_measurement_trip_signal_replay_time ON canonical_measurement(vehicle_id,trip_id,signal,ts_replay_ns)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_event_trip_time ON overlay_event(vehicle_id,trip_id,ts_replay_ns)")
    connection.commit()
    _build_1hz(connection)
    _build_rollups(connection)
    _build_event_windows(connection)
    _build_deviations(connection)
    connection.commit()
    return {
        name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in ("derived_1hz", "trip_rollup", "event_window", "deviation_flag")
    }


def hash_outputs(connection: sqlite3.Connection) -> dict[str, dict[str, object]]:
    order_by = {
        "derived_1hz": "vehicle_id,trip_id,signal,bucket_start_ns",
        "trip_rollup": "vehicle_id,trip_id,metric",
        "event_window": "event_id,offset_seconds,signal",
        "deviation_flag": "vehicle_id,trip_id,signal,bucket_start_ns,rule_id",
    }
    results = {}
    for table, ordering in order_by.items():
        digest = hashlib.sha256()
        cursor = connection.execute(f"SELECT * FROM {table} ORDER BY {ordering}")
        count = 0
        while rows := cursor.fetchmany(10000):
            for row in rows:
                digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
                count += 1
        results[table] = {"rows": count, "sha256": digest.hexdigest()}
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-reproducible", action="store_true", help="rebuild a second time and compare all derived output hashes")
    args = parser.parse_args()
    if not DATABASE.exists():
        raise SystemExit(f"missing canonical database: {DATABASE}")
    connection = initialize_database(DATABASE, load_catalogue())
    try:
        result = build(connection)
        first_hashes = hash_outputs(connection)
        if args.verify_reproducible:
            build(connection)
            second_hashes = hash_outputs(connection)
            if first_hashes != second_hashes:
                raise RuntimeError("derived outputs changed between identical rebuilds")
        else:
            second_hashes = first_hashes
        HASH_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        HASH_MANIFEST.write_text(
            json.dumps(second_hashes, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["reproducibility_verified"] = args.verify_reproducible
        result["output_hashes"] = second_hashes
    finally:
        connection.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
