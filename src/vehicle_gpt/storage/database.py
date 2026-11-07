"""SQLite schema and deterministic canonical measurement writer."""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "src/vehicle_gpt/storage/schema.sql"
CATALOGUE = ROOT / "configs/signals.yaml"
BATCH_SIZE = 10_000


def load_catalogue(path: Path = CATALOGUE) -> dict[str, object]:
    import yaml

    with path.open(encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict) or not isinstance(data.get("signals"), dict):
        raise ValueError(f"invalid signal catalogue: {path}")
    return data


def initialize_database(path: Path, catalogue: Mapping[str, object]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    for name, spec in catalogue["signals"].items():
        connection.execute(
            """INSERT INTO signal_catalog(signal,canonical_unit,data_type,
               expected_sampling_hz,description) VALUES (?,?,?,?,?)
               ON CONFLICT(signal) DO UPDATE SET canonical_unit=excluded.canonical_unit,
               data_type=excluded.data_type,expected_sampling_hz=excluded.expected_sampling_hz,
               description=excluded.description""",
            (
                name,
                spec["unit"],
                spec["data_type"],
                spec.get("expected_sampling_hz"),
                spec["description"],
            ),
        )
    connection.commit()
    return connection


def register_vehicle(
    connection: sqlite3.Connection,
    vehicle_id: str,
    source_vehicle_key: str,
    source_dataset: str,
    make: str | None,
    model: str | None,
    model_year: int | None,
    powertrain: str | None,
    identity_evidence: str,
) -> None:
    connection.execute(
        """INSERT INTO vehicle_registry(vehicle_id,source_vehicle_key,source_dataset,
           make,model,model_year,powertrain,identity_evidence) VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(vehicle_id) DO NOTHING""",
        (
            vehicle_id,
            source_vehicle_key,
            source_dataset,
            make,
            model,
            model_year,
            powertrain,
            identity_evidence,
        ),
    )


def register_trip(
    connection: sqlite3.Connection,
    vehicle_id: str,
    trip_id: str,
    source_trip_key: str,
    source_dataset: str,
    timestamp_basis: str,
    provenance: str = "real",
) -> None:
    connection.execute(
        """INSERT INTO trip_registry(vehicle_id,trip_id,source_trip_key,source_dataset,
           timestamp_basis,provenance) VALUES (?,?,?,?,?,?)
           ON CONFLICT(vehicle_id,trip_id) DO NOTHING""",
        (
            vehicle_id,
            trip_id,
            source_trip_key,
            source_dataset,
            timestamp_basis,
            provenance,
        ),
    )


def update_trip_bounds(
    connection: sqlite3.Connection,
    vehicle_id: str,
    trip_id: str,
    source_start: str,
    source_end: str,
    replay_start: str | None,
    replay_end: str | None,
) -> None:
    connection.execute(
        """UPDATE trip_registry SET ts_source_start=?,ts_source_end=?,
           ts_replay_start=?,ts_replay_end=? WHERE vehicle_id=? AND trip_id=?""",
        (source_start, source_end, replay_start, replay_end, vehicle_id, trip_id),
    )


def _quality(value: float | None, flag: str) -> str:
    return flag if value is None or math.isfinite(value) else "source_nonfinite"


def insert_measurements(
    connection: sqlite3.Connection, rows: Iterable[Mapping[str, object]]
) -> int:
    sql = """INSERT INTO canonical_measurement(
        vehicle_id,trip_id,signal,unit,ts_source,ts_source_seconds,ts_replay,
        ts_replay_ns,timestamp_basis,value,quality_flag,provenance,source_dataset,
        source_file,source_row,source_field,source_unit,source_value
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    pending = []
    inserted = 0
    for row in rows:
        value = row["value"]
        if value is not None and not math.isfinite(float(value)):
            value = None
        quality = _quality(value, str(row.get("quality_flag", "ok")))
        pending.append(
            (
                row["vehicle_id"],
                row["trip_id"],
                row["signal"],
                row["unit"],
                row["ts_source"],
                row.get("ts_source_seconds"),
                row.get("ts_replay"),
                row.get("ts_replay_ns"),
                row["timestamp_basis"],
                value,
                quality,
                "real",
                row["source_dataset"],
                row["source_file"],
                row["source_row"],
                row["source_field"],
                row["source_unit"],
                row.get("source_value"),
            )
        )
        if len(pending) >= BATCH_SIZE:
            connection.executemany(sql, pending)
            inserted += len(pending)
            pending.clear()
    if pending:
        connection.executemany(sql, pending)
        inserted += len(pending)
    return inserted


def check_value(value: float | None, valid_range: list[object] | None) -> str:
    if value is None:
        return "source_missing"
    if valid_range is None:
        return "ok"
    lower, upper = valid_range
    if lower is not None and value < float(lower):
        return "out_of_range"
    if upper is not None and value > float(upper):
        return "out_of_range"
    return "ok"


def convert_source_value(
    token: str, mapping: Mapping[str, object], spec: Mapping[str, object]
) -> tuple[float | None, str]:
    raw = token.strip()
    if raw == "":
        return None, "source_blank"
    low = raw.lower()
    if low in ("nan", "na", "null", "none"):
        return None, "source_nan"
    if spec["data_type"] == "boolean" and low in ("true", "false"):
        value = 1.0 if low == "true" else 0.0
    else:
        try:
            value = float(raw)
        except ValueError:
            return None, "malformed_value"
        if not math.isfinite(value):
            return None, "source_nonfinite"
    rule = str(mapping.get("conversion", "identity"))
    if rule == "identity" or rule.startswith("true ->"):
        pass
    elif rule == "value / 3.6":
        value /= 3.6
    elif rule == "value * 1000":
        value *= 1000.0
    elif rule == "((raw * 0.01) - 67.67) / 3.6":
        value = ((value * 0.01) - 67.67) / 3.6
    else:
        raise ValueError(f"unsupported conversion rule: {rule}")
    return value, check_value(value, spec.get("valid_range"))


def naive_datetime_ns(value: datetime) -> int:
    """Sortable, timezone-free coordinate for source wall-clock datetimes."""
    epoch = datetime(1970, 1, 1)
    delta = value - epoch
    return ((delta.days * 86400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1000


def datetime_iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")
