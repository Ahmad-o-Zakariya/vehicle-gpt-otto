"""Streaming VED 7z reader and selected-vehicle canonical loader."""

from __future__ import annotations

import csv
import ctypes
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from vehicle_gpt.storage.database import (
    datetime_iso,
    insert_measurements,
    naive_datetime_ns,
    register_trip,
    register_vehicle,
    update_trip_bounds,
)


class _Libarchive:
    def __init__(self) -> None:
        try:
            self.lib = ctypes.CDLL("libarchive.so.13")
        except OSError as exc:
            raise RuntimeError(
                "VED loading requires libarchive.so.13 to read supplied 7z archives"
            ) from exc
        lib = self.lib
        lib.archive_read_new.restype = ctypes.c_void_p
        for name in ("archive_read_support_filter_all", "archive_read_support_format_all"):
            getattr(lib, name).argtypes = [ctypes.c_void_p]
            getattr(lib, name).restype = ctypes.c_int
        lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        lib.archive_read_open_filename.restype = ctypes.c_int
        lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.archive_read_next_header.restype = ctypes.c_int
        lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
        lib.archive_entry_pathname.restype = ctypes.c_char_p
        lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        lib.archive_read_data.restype = ctypes.c_ssize_t
        lib.archive_error_string.argtypes = [ctypes.c_void_p]
        lib.archive_error_string.restype = ctypes.c_char_p
        lib.archive_read_free.argtypes = [ctypes.c_void_p]
        lib.archive_read_free.restype = ctypes.c_int


def iter_7z_csv(archive_path: Path) -> Iterator[tuple[str, Path]]:
    """Yield each CSV entry as a temporary file without changing the archive."""
    adapter = _Libarchive()
    lib = adapter.lib
    archive = lib.archive_read_new()
    if not archive:
        raise RuntimeError("libarchive failed to allocate a reader")
    try:
        lib.archive_read_support_filter_all(archive)
        lib.archive_read_support_format_all(archive)
        status = lib.archive_read_open_filename(archive, str(archive_path).encode(), 1 << 15)
        if status != 0:
            detail = lib.archive_error_string(archive)
            raise RuntimeError(f"cannot open {archive_path}: {detail!r}")
        entry = ctypes.c_void_p()
        with tempfile.TemporaryDirectory(prefix="vehicle-gpt-ved-") as temp_dir:
            root = Path(temp_dir)
            while True:
                status = lib.archive_read_next_header(archive, ctypes.byref(entry))
                if status == 1:
                    break
                if status < 0:
                    detail = lib.archive_error_string(archive)
                    raise RuntimeError(f"archive read error in {archive_path}: {detail!r}")
                name = lib.archive_entry_pathname(entry).decode("utf-8", errors="replace")
                if not name.lower().endswith(".csv"):
                    _drain_entry(lib, archive)
                    continue
                destination = root / Path(name).name
                with destination.open("wb") as output:
                    _copy_entry(lib, archive, output)
                yield name, destination
                destination.unlink(missing_ok=True)
    finally:
        lib.archive_read_free(archive)


def _copy_entry(lib: ctypes.CDLL, archive: int, output) -> None:
    buffer = ctypes.create_string_buffer(1 << 20)
    while True:
        count = lib.archive_read_data(archive, buffer, len(buffer))
        if count == 0:
            return
        if count < 0:
            detail = lib.archive_error_string(archive)
            raise RuntimeError(f"archive entry read failed: {detail!r}")
        output.write(buffer.raw[:count])


def _drain_entry(lib: ctypes.CDLL, archive: int) -> None:
    buffer = ctypes.create_string_buffer(1 << 20)
    while lib.archive_read_data(archive, buffer, len(buffer)) > 0:
        pass


def _signal_mappings(catalogue: dict[str, object], vehicle_id: int) -> dict[str, tuple[str, dict[str, object], dict[str, object]]]:
    selected = {
        455: {
            "vehicle.speed", "vehicle.latitude", "vehicle.longitude",
            "vehicle.ambient_temperature", "battery.voltage", "battery.current",
            "battery.soc", "hvac.heater_power", "hvac.ac_power",
        },
        119: {
            "vehicle.speed", "vehicle.latitude", "vehicle.longitude",
            "vehicle.ambient_temperature", "vehicle.fuel_rate",
        },
    }[vehicle_id]
    result = {}
    for signal in selected:
        spec = catalogue["signals"][signal]
        mapping = next(
            item for item in spec["source_mappings"] if item["dataset"] == "ved"
        )
        result[mapping["field"]] = (signal, spec, mapping)
    return result


def _replay_time(day_num: str, timestamp_ms: str) -> datetime:
    origin = datetime(2017, 11, 1)
    return origin + timedelta(days=float(day_num), milliseconds=float(timestamp_ms))


def load_ved(connection, catalogue: dict[str, object], root: Path) -> dict[str, object]:
    data_dir = root / "Data"
    archives = sorted(data_dir.glob("VED_DynamicData_Part*.7z"))
    if len(archives) != 2:
        raise FileNotFoundError(f"expected two VED dynamic archives under {data_dir}; found {len(archives)}")
    for vehicle_id, powertrain in ((455, "EV"), (119, "ICE")):
        register_vehicle(
            connection,
            f"ved:{vehicle_id}",
            str(vehicle_id),
            "ved",
            "Nissan" if vehicle_id == 455 else None,
            "Leaf" if vehicle_id == 455 else None,
            None,
            powertrain,
            "VED static vehicle registry",
        )
    connection.commit()

    report: dict[str, object] = {
        "dataset": "ved",
        "archives": len(archives),
        "selected_vehicle_ids": [455, 119],
        "source_rows": 0,
        "canonical_rows": 0,
        "rejected_rows": 0,
        "missing_values": 0,
        "source_files": 0,
    }
    trip_bounds: dict[tuple[str, str], list[object]] = {}

    for archive in archives:
        for member, temp_csv in iter_7z_csv(archive):
            report["source_files"] = int(report["source_files"]) + 1
            source_file = f"{archive.relative_to(root.parent).as_posix()}::{member}"
            with temp_csv.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                required = {"DayNum", "VehId", "Trip", "Timestamp(ms)"}
                if not reader.fieldnames or not required.issubset(reader.fieldnames):
                    raise ValueError(f"unexpected VED CSV header: {source_file}")
                file_rows = []
                for source_row, row in enumerate(reader, 2):
                    try:
                        vehicle = int(row["VehId"])
                        if vehicle not in (455, 119):
                            continue
                        trip_key = row["Trip"].strip()
                        timestamp_token = row["Timestamp(ms)"].strip()
                        day_token = row["DayNum"].strip()
                        timestamp_ms = float(timestamp_token)
                        replay = _replay_time(day_token, timestamp_token)
                    except (TypeError, ValueError, KeyError):
                        report["rejected_rows"] = int(report["rejected_rows"]) + 1
                        continue
                    report["source_rows"] = int(report["source_rows"]) + 1
                    vehicle_key = f"ved:{vehicle}"
                    trip_id = f"trip:{trip_key}"
                    register_trip(
                        connection,
                        vehicle_key,
                        trip_id,
                        trip_key,
                        "ved",
                        "daynum_plus_elapsed_milliseconds",
                    )
                    bounds_key = (vehicle_key, trip_id)
                    current = trip_bounds.get(bounds_key)
                    source_time = f"DayNum={day_token};Timestamp(ms)={timestamp_token}"
                    if current is None:
                        trip_bounds[bounds_key] = [
                            source_time, source_time, replay, replay,
                        ]
                    else:
                        if replay < current[2]:
                            current[0], current[2] = source_time, replay
                        if replay > current[3]:
                            current[1], current[3] = source_time, replay

                    rows = []
                    for field, (signal, spec, mapping) in _signal_mappings(catalogue, vehicle).items():
                        if field not in row:
                            raise ValueError(f"VED field {field!r} missing from {source_file}")
                        value, quality = _convert(row[field], mapping, spec)
                        if value is None:
                            report["missing_values"] = int(report["missing_values"]) + 1
                        rows.append(
                            {
                                "vehicle_id": vehicle_key,
                                "trip_id": trip_id,
                                "signal": signal,
                                "unit": spec["unit"],
                                "ts_source": source_time,
                                "ts_source_seconds": timestamp_ms / 1000.0,
                                "ts_replay": replay.isoformat(timespec="microseconds"),
                                "ts_replay_ns": naive_datetime_ns(replay),
                                "timestamp_basis": "wall_clock_naive_local_from_daynum_plus_elapsed_ms",
                                "value": value,
                                "quality_flag": quality,
                                "source_dataset": "ved",
                                "source_file": source_file,
                                "source_row": source_row,
                                "source_field": field,
                                "source_unit": mapping["source_unit"],
                                "source_value": row[field],
                            }
                        )
                    file_rows.extend(rows)
                    if len(file_rows) >= 20_000:
                        report["canonical_rows"] = int(report["canonical_rows"]) + insert_measurements(connection, file_rows)
                        file_rows.clear()
                if file_rows:
                    report["canonical_rows"] = int(report["canonical_rows"]) + insert_measurements(connection, file_rows)
            connection.commit()

    for (vehicle_key, trip_id), values in trip_bounds.items():
        update_trip_bounds(
            connection,
            vehicle_key,
            trip_id,
            values[0],
            values[1],
            values[2].isoformat(timespec="microseconds"),
            values[3].isoformat(timespec="microseconds"),
        )
    connection.commit()
    return report


def _convert(token: str, mapping: dict[str, object], spec: dict[str, object]):
    from vehicle_gpt.storage.database import convert_source_value

    return convert_source_value(token, mapping, spec)
