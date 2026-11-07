#!/usr/bin/env python3
"""Derive per-trip coverage and measured per-vehicle signal capability."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.storage.database import initialize_database, load_catalogue

DATABASE = ROOT / "data/processed/vehicle_gpt.sqlite"


def _median(histogram: Counter[float]) -> float | None:
    total = sum(histogram.values())
    if not total:
        return None
    targets = {(total - 1) // 2, total // 2}
    values = []
    cumulative = 0
    for value, count in sorted(histogram.items()):
        cumulative += count
        while targets and cumulative > min(targets):
            target = min(targets)
            values.append(value)
            targets.remove(target)
    return sum(values) / len(values)


def _expected_rate(catalogue, dataset: str, signal: str) -> float | None:
    spec = catalogue["signals"][signal]
    for mapping in spec.get("source_mappings", []):
        if mapping["dataset"] == dataset and mapping.get("expected_sampling_hz"):
            return float(mapping["expected_sampling_hz"])
    value = spec.get("expected_sampling_hz")
    return float(value) if value else None


def build(connection, catalogue) -> dict[str, int]:
    connection.execute("DELETE FROM signal_coverage")
    connection.execute("DELETE FROM vehicle_capability")
    cursor = connection.execute(
        """SELECT vehicle_id,trip_id,signal,unit,source_dataset,ts_source_seconds,
                  ts_replay_ns,value,quality_flag,provenance
           FROM canonical_measurement
           ORDER BY vehicle_id,trip_id,signal,ts_source_seconds"""
    )
    summary = {"trip_signal_rows": 0, "vehicle_signal_rows": 0}
    vehicle_totals = {}
    key = None
    state = None

    def finish(group_key, group):
        if group_key is None:
            return
        vehicle, trip, signal = group_key
        duration = max(0.0, group["last_t"] - group["first_t"])
        median_interval = _median(group["intervals"])
        expected_hz = _expected_rate(catalogue, group["dataset"], signal)
        expected_count = (duration * expected_hz + 1.0) if expected_hz else None
        coverage = min(1.0, group["valid"] / expected_count) if expected_count else None
        connection.execute(
            """INSERT INTO signal_coverage(vehicle_id,trip_id,signal,unit,
               first_ts_replay_ns,last_ts_replay_ns,expected_interval_seconds,
               observed_interval_median_seconds,sample_count,missing_count,missing_rate,
               coverage,quality_summary_json,provenance) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                vehicle, trip, signal, group["unit"], group["first_replay"],
                group["last_replay"], (1.0 / expected_hz) if expected_hz else None,
                median_interval, group["rows"], group["missing"],
                group["missing"] / group["rows"] if group["rows"] else None,
                coverage, json.dumps(dict(sorted(group["quality"].items())), sort_keys=True),
                group["provenance"],
            ),
        )
        summary["trip_signal_rows"] += 1
        vkey = (vehicle, signal)
        total = vehicle_totals.setdefault(
            vkey,
            {
                "unit": group["unit"], "dataset": group["dataset"],
                "first_replay": group["first_replay"], "last_replay": group["last_replay"],
                "rows": 0, "missing": 0, "valid": 0, "expected": 0.0,
                "has_expected": False, "interval_seconds": 0.0, "interval_count": 0,
                "quality": Counter(), "provenance": group["provenance"],
            },
        )
        total["rows"] += group["rows"]
        total["missing"] += group["missing"]
        total["valid"] += group["valid"]
        total["quality"].update(group["quality"])
        if group["first_replay"] is not None:
            if total["first_replay"] is None or group["first_replay"] < total["first_replay"]:
                total["first_replay"] = group["first_replay"]
            if total["last_replay"] is None or group["last_replay"] > total["last_replay"]:
                total["last_replay"] = group["last_replay"]
        if expected_hz:
            total["has_expected"] = True
            total["expected"] += duration * expected_hz + 1.0
        positive_intervals = [(dt, count) for dt, count in group["intervals"].items() if dt > 0]
        total["interval_seconds"] += sum(dt * count for dt, count in positive_intervals)
        total["interval_count"] += sum(count for _, count in positive_intervals)

    for row in cursor:
        row_key = (row[0], row[1], row[2])
        if row_key != key:
            finish(key, state)
            key = row_key
            state = {
                "unit": row[3], "dataset": row[4], "first_t": row[5], "last_t": row[5],
                "previous_t": row[5], "first_replay": row[6], "last_replay": row[6],
                "rows": 0, "missing": 0, "valid": 0, "intervals": Counter(),
                "quality": Counter(), "provenance": row[9],
            }
        elif row[5] is not None and state["previous_t"] is not None:
            interval = round(float(row[5]) - float(state["previous_t"]), 6)
            if interval >= 0:
                state["intervals"][interval] += 1
        if row[5] is not None:
            state["last_t"] = float(row[5])
            state["previous_t"] = float(row[5])
        if row[6] is not None:
            state["last_replay"] = row[6]
        state["rows"] += 1
        if row[7] is None:
            state["missing"] += 1
        else:
            state["valid"] += 1
        state["quality"][row[8]] += 1
    finish(key, state)

    for (vehicle, signal), total in sorted(vehicle_totals.items()):
        expected = total["expected"] if total["has_expected"] else None
        coverage = min(1.0, total["valid"] / expected) if expected else None
        interval = (
            total["interval_seconds"] / total["interval_count"]
            if total["interval_count"] else None
        )
        observed_hz = (1.0 / interval) if interval and interval > 0 else None
        connection.execute(
            """INSERT INTO vehicle_capability(vehicle_id,signal,unit,source_dataset,
               first_ts_replay_ns,last_ts_replay_ns,expected_sampling_hz,observed_sampling_hz,
               sample_count,missing_rate,coverage,quality_summary_json,provenance)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                vehicle, signal, total["unit"], total["dataset"], total["first_replay"],
                total["last_replay"], _expected_rate(catalogue, total["dataset"], signal),
                observed_hz, total["rows"], total["missing"] / total["rows"], coverage,
                json.dumps(dict(sorted(total["quality"].items())), sort_keys=True),
                total["provenance"],
            ),
        )
        summary["vehicle_signal_rows"] += 1
    connection.commit()
    return summary


def main() -> int:
    if not DATABASE.exists():
        raise SystemExit(f"missing canonical database: {DATABASE}")
    catalogue = load_catalogue()
    connection = initialize_database(DATABASE, catalogue)
    try:
        result = build(connection, catalogue)
    finally:
        connection.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
