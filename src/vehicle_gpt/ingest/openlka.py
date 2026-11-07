"""Import timestamped OpenLKA sample telemetry and observed LKA state changes."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from vehicle_gpt.storage.database import (
    convert_source_value,
    insert_measurements,
    naive_datetime_ns,
    register_trip,
    register_vehicle,
    update_trip_bounds,
)


def _timestamp(token: str):
    value = Decimal(token)
    nanoseconds = int(value)
    seconds, remainder = divmod(nanoseconds, 1_000_000_000)
    date = datetime.fromtimestamp(seconds, timezone.utc).replace(
        microsecond=remainder // 1000
    )
    return nanoseconds, date.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _signal_fields(catalogue):
    return {
        mapping["field"]: (signal, spec, mapping)
        for signal, spec in catalogue["signals"].items()
        for mapping in spec["source_mappings"]
        if mapping["dataset"] == "openlka"
    }


def load_openlka(connection, catalogue, root: Path) -> dict[str, object]:
    fields = _signal_fields(catalogue)
    files = sorted(root.rglob("*.csv"))
    report = {
        "dataset": "openlka",
        "files": 0,
        "files_with_unix_time": 0,
        "source_rows": 0,
        "canonical_rows": 0,
        "observed_state_changes": 0,
        "rejected_rows": 0,
        "missing_values": 0,
    }
    for path in files:
        clip_key = path.relative_to(root).as_posix()
        clip_id = hashlib.sha256(clip_key.encode("utf-8")).hexdigest()[:16]
        vehicle_id = f"openlka:clip:{clip_id}"
        trip_id = "clip:1"
        model_hint = path.relative_to(root).parts[0]
        register_vehicle(
            connection,
            vehicle_id,
            clip_key,
            "openlka",
            None,
            model_hint,
            None,
            None,
            "clip-level identity; physical vehicle identity is not asserted",
        )
        register_trip(
            connection,
            vehicle_id,
            trip_id,
            clip_key,
            "openlka",
            "unix_epoch_ns_utc_or_clip_relative_seconds",
        )
        report["files"] += 1
        batch = []
        previous_state = None
        previous_time = None
        first_source = last_source = None
        first_replay = last_replay = None

        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                report["rejected_rows"] += 1
                continue
            has_unix_time = "unix_time" in reader.fieldnames
            if has_unix_time:
                report["files_with_unix_time"] += 1
            for source_row, row in enumerate(reader, 2):
                if None in row:
                    report["rejected_rows"] += 1
                    continue
                time_token = (row.get("unix_time") or "").strip()
                relative_token = (row.get("Time") or "").strip()
                replay = None
                replay_ns = None
                if time_token and time_token.lower() not in ("nan", "null"):
                    try:
                        replay_ns, replay = _timestamp(time_token)
                        source_time = time_token
                        source_seconds = float(Decimal(time_token) / Decimal(1_000_000_000))
                        timestamp_basis = "unix_epoch_ns_utc"
                    except (ValueError, ArithmeticError, OverflowError):
                        report["rejected_rows"] += 1
                        continue
                elif relative_token:
                    try:
                        source_seconds = float(relative_token)
                    except ValueError:
                        report["rejected_rows"] += 1
                        continue
                    source_time = relative_token
                    timestamp_basis = "clip_relative_seconds_wall_clock_unavailable"
                else:
                    report["rejected_rows"] += 1
                    continue

                report["source_rows"] += 1
                if first_source is None:
                    first_source = source_time
                    first_replay = replay
                last_source = source_time
                last_replay = replay
                for field, (signal, spec, mapping) in fields.items():
                    if field not in row:
                        continue
                    value, quality = convert_source_value(row[field], mapping, spec)
                    if value is None:
                        report["missing_values"] += 1
                    batch.append(
                        {
                            "vehicle_id": vehicle_id,
                            "trip_id": trip_id,
                            "signal": signal,
                            "unit": spec["unit"],
                            "ts_source": source_time,
                            "ts_source_seconds": source_seconds,
                            "ts_replay": replay,
                            "ts_replay_ns": replay_ns,
                            "timestamp_basis": timestamp_basis,
                            "value": value,
                            "quality_flag": quality,
                            "source_dataset": "openlka",
                            "source_file": path.relative_to(root.parent).as_posix(),
                            "source_row": source_row,
                            "source_field": field,
                            "source_unit": mapping["source_unit"],
                            "source_value": row[field],
                        }
                    )
                    if len(batch) >= 20_000:
                        report["canonical_rows"] += insert_measurements(connection, batch)
                        batch.clear()

                state_token = (row.get("op_lat_enable") or "").strip().lower()
                if state_token in ("true", "false"):
                    if previous_state is not None and previous_state != state_token:
                        event_id = f"openlka:{clip_id}:state:{source_row}"
                        metadata = {
                            "signal": "op_lat_enable",
                            "from": previous_state,
                            "to": state_token,
                            "interpretation": "observed controller enable-state transition; reason unavailable",
                            "source_file": path.relative_to(root.parent).as_posix(),
                            "source_row": source_row,
                        }
                        connection.execute(
                            """INSERT INTO overlay_event(event_id,vehicle_id,trip_id,event_type,
                               ts_source,ts_replay,ts_replay_ns,provenance,injection_id,
                               event_metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (
                                event_id,
                                vehicle_id,
                                trip_id,
                                "adas.lateral_control_enable_state_change",
                                source_time,
                                replay,
                                replay_ns,
                                "real",
                                None,
                                json.dumps(metadata, sort_keys=True),
                            ),
                        )
                        report["observed_state_changes"] += 1
                    previous_state = state_token
                previous_time = source_seconds

        if batch:
            report["canonical_rows"] += insert_measurements(connection, batch)
        update_trip_bounds(
            connection,
            vehicle_id,
            trip_id,
            first_source or "",
            last_source or "",
            first_replay,
            last_replay,
        )
        connection.commit()
    return report
