"""Read comma2k19 NumPy arrays and replay verified Toyota CAN mappings."""

from __future__ import annotations

import ast
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DBC_NAME = "toyota_new_mc_pt_generated"
DBC_REFERENCE = "https://github.com/commaai/opendbc"
CAN_STEERING_ANGLE = 37
CAN_WHEEL_SPEEDS = 170
TOLERANCE = 1e-9


@dataclass(frozen=True)
class NpyArray:
    dtype: str
    shape: tuple[int, ...]
    values: list[float | int | bytes]


def read_npy(path: Path) -> NpyArray:
    """Read the little-endian NPY v1 arrays in the supplied segment."""
    with path.open("rb") as source:
        if source.read(6) != b"\x93NUMPY":
            raise ValueError(f"not a NumPy array: {path}")
        version = source.read(2)
        if version != b"\x01\x00":
            raise ValueError(f"unsupported NPY version {version!r}: {path}")
        header_length_bytes = source.read(2)
        if len(header_length_bytes) != 2:
            raise ValueError(f"truncated NPY header: {path}")
        header_length = struct.unpack("<H", header_length_bytes)[0]
        header = ast.literal_eval(source.read(header_length).decode("latin-1").strip())
        if header["fortran_order"]:
            raise ValueError(f"Fortran-order arrays are unsupported: {path}")
        dtype = header["descr"]
        shape = tuple(header["shape"])
        fmt = {"<f8": "<d", "<i8": "<q", "|S8": "8s"}.get(dtype)
        if fmt is None:
            raise ValueError(f"unsupported dtype {dtype!r}: {path}")
        payload = source.read()
    item_size = struct.calcsize(fmt)
    expected_count = math.prod(shape)
    if len(payload) != expected_count * item_size:
        raise ValueError(f"array payload size mismatch: {path}")
    values = [item[0] for item in struct.iter_unpack(fmt, payload)]
    return NpyArray(dtype, shape, values)


def decode_motorola(payload: bytes, start_bit: int, bit_length: int, signed: bool = False) -> int:
    """Decode one DBC big-endian signal using the DBC sawtooth bit numbering."""
    if bit_length <= 0 or len(payload) != 8:
        raise ValueError("DBC signals require an 8-byte payload and positive bit length")
    bit = start_bit
    value = 0
    for _ in range(bit_length):
        if bit < 0 or bit >= len(payload) * 8:
            raise ValueError("DBC signal exceeds the CAN payload")
        value = (value << 1) | ((payload[bit // 8] >> (bit % 8)) & 1)
        bit = bit + 15 if bit % 8 == 0 else bit - 1
    if signed and value & (1 << (bit_length - 1)):
        value -= 1 << bit_length
    return value


def decode_steering(payload: bytes) -> float:
    whole = decode_motorola(payload, 3, 12, signed=True) * 1.5
    fraction = decode_motorola(payload, 39, 4, signed=True) * 0.1
    return whole + fraction


def decode_wheel_speeds(payload: bytes) -> dict[str, float]:
    starts = {
        "vehicle.wheel_speed_fl": 23,
        "vehicle.wheel_speed_fr": 7,
        "vehicle.wheel_speed_rl": 55,
        "vehicle.wheel_speed_rr": 39,
    }
    return {
        name: (decode_motorola(payload, start, 16) * 0.01 - 67.67) / 3.6
        for name, start in starts.items()
    }


def _read_scalar(path: Path) -> list[float]:
    array = read_npy(path)
    if array.dtype != "<f8" or len(array.shape) != 1:
        raise ValueError(f"expected one-dimensional float64 array: {path}")
    return [float(v) for v in array.values]


def _read_matrix(path: Path, width: int) -> list[list[float]]:
    array = read_npy(path)
    if array.dtype != "<f8" or len(array.shape) != 2 or array.shape[1] != width:
        raise ValueError(f"expected float64 matrix with width {width}: {path}")
    return [
        [float(v) for v in array.values[i * width : (i + 1) * width]]
        for i in range(array.shape[0])
    ]


def verify_segment(segment: Path) -> dict[str, object]:
    raw = segment / "processed_log/CAN/raw_can"
    times = _read_scalar(raw / "t")
    addresses = read_npy(raw / "address").values
    payloads = read_npy(raw / "data").values
    if not (len(times) == len(addresses) == len(payloads)):
        raise ValueError("raw CAN arrays have different lengths")

    steering_frames: dict[float, float] = {}
    wheel_frames: dict[float, dict[str, float]] = {}
    id_counts: dict[str, int] = {}
    for timestamp, address, payload in zip(times, addresses, payloads):
        if not isinstance(address, int) or not isinstance(payload, bytes):
            raise ValueError("unexpected raw CAN array element type")
        can_id = address & 0x7FF
        id_counts[str(can_id)] = id_counts.get(str(can_id), 0) + 1
        if can_id == CAN_STEERING_ANGLE:
            steering_frames[round(timestamp, 6)] = decode_steering(payload)
        elif can_id == CAN_WHEEL_SPEEDS:
            wheel_frames[round(timestamp, 6)] = decode_wheel_speeds(payload)

    steering_times = _read_scalar(segment / "processed_log/CAN/steering_angle/t")
    steering_values = _read_scalar(segment / "processed_log/CAN/steering_angle/value")
    wheel_times = _read_scalar(segment / "processed_log/CAN/wheel_speed/t")
    wheel_values = _read_matrix(segment / "processed_log/CAN/wheel_speed/value", 4)
    if not (len(steering_times) == len(steering_values) and len(wheel_times) == len(wheel_values)):
        raise ValueError("processed CAN time/value arrays have different lengths")

    steering_diffs = []
    for timestamp, expected in zip(steering_times, steering_values):
        actual = steering_frames.get(round(timestamp, 6))
        if actual is None:
            raise ValueError("steering processed sample has no raw CAN frame at its timestamp")
        steering_diffs.append(abs(actual - expected))

    wheel_names = (
        "vehicle.wheel_speed_fl",
        "vehicle.wheel_speed_fr",
        "vehicle.wheel_speed_rl",
        "vehicle.wheel_speed_rr",
    )
    wheel_diffs: list[float] = []
    for timestamp, expected_values in zip(wheel_times, wheel_values):
        actual = wheel_frames.get(round(timestamp, 6))
        if actual is None:
            raise ValueError("wheel-speed processed sample has no raw CAN frame at its timestamp")
        wheel_diffs.extend(
            abs(actual[name] - expected_values[index])
            for index, name in enumerate(wheel_names)
        )

    result: dict[str, object] = {
        "dbc": DBC_NAME,
        "dbc_reference": DBC_REFERENCE,
        "segment": segment.as_posix(),
        "raw_frame_count": len(times),
        "can_id_counts": {key: id_counts.get(key, 0) for key in ("37", "170", "180")},
        "steering_samples_compared": len(steering_diffs),
        "wheel_speed_samples_compared": len(wheel_times),
        "wheel_speed_components_compared": len(wheel_diffs),
        "steering_max_abs_error_deg": max(steering_diffs, default=None),
        "wheel_speed_max_abs_error_mps": max(wheel_diffs, default=None),
        "tolerance": TOLERANCE,
        "passed": bool(steering_diffs and wheel_diffs)
        and max(steering_diffs) <= TOLERANCE
        and max(wheel_diffs) <= TOLERANCE,
    }
    if not result["passed"]:
        raise ValueError(f"raw CAN mapping validation failed: {result}")
    return result


def iter_decoded_samples(segment: Path) -> Iterator[dict[str, object]]:
    """Yield source-timed decoded steering and wheel-speed signal rows."""
    raw = segment / "processed_log/CAN/raw_can"
    times = _read_scalar(raw / "t")
    addresses = read_npy(raw / "address").values
    payloads = read_npy(raw / "data").values
    for row_index, (timestamp, address, payload) in enumerate(zip(times, addresses, payloads), 1):
        can_id = int(address) & 0x7FF
        if can_id == CAN_STEERING_ANGLE:
            yield {
                "source_row": row_index,
                "ts_source": repr(timestamp),
                "ts_source_seconds": timestamp,
                "timestamp_basis": "device_boot_seconds",
                "source_field": "0x025/STEER_ANGLE_SENSOR/STEER_ANGLE+STEER_FRACTION",
                "source_value": bytes(payload).hex(),
                "signal": "vehicle.steering_angle",
                "unit": "deg",
                "source_unit": "deg",
                "value": decode_steering(bytes(payload)),
            }
        elif can_id == CAN_WHEEL_SPEEDS:
            for signal, value in decode_wheel_speeds(bytes(payload)).items():
                suffix = signal.rsplit("_", 1)[-1].upper()
                yield {
                    "source_row": row_index,
                    "ts_source": repr(timestamp),
                    "ts_source_seconds": timestamp,
                    "timestamp_basis": "device_boot_seconds",
                    "source_field": f"0x0AA/WHEEL_SPEEDS/WHEEL_SPEED_{suffix}",
                    "source_value": bytes(payload).hex(),
                    "signal": signal,
                    "unit": "m/s",
                    "source_unit": "km/h",
                    "value": value,
                }


def load_comma2k19(connection, catalogue: dict[str, object], segment: Path, repository_root: Path) -> dict[str, object]:
    """Insert decoded real steering and wheel speeds plus the supplied CAN speed."""
    from vehicle_gpt.storage.database import (
        insert_measurements,
        register_trip,
        register_vehicle,
        update_trip_bounds,
    )

    route = segment.parent.name
    dongle = route.split("|", 1)[0]
    segment_id = segment.name
    vehicle_id = f"comma2k19:rav4:{dongle}"
    trip_id = f"segment:{segment_id}"
    register_vehicle(
        connection,
        vehicle_id,
        dongle,
        "comma2k19",
        "Toyota",
        "RAV4",
        None,
        None,
        "comma2k19 README maps this dongle ID to a RAV4; model year/trim unknown",
    )
    register_trip(
        connection,
        vehicle_id,
        trip_id,
        f"{route}/{segment_id}",
        "comma2k19",
        "device_boot_seconds; wall-clock segment alignment unavailable",
    )
    connection.commit()

    report = {
        "dataset": "comma2k19",
        "vehicle_id": vehicle_id,
        "trip_id": trip_id,
        "canonical_rows": 0,
        "processed_speed_rows": 0,
        "raw_frames_decoded": 0,
    }
    source_start = source_end = None
    batch = []
    source_prefix = segment.relative_to(repository_root).as_posix()
    for decoded in iter_decoded_samples(segment):
        timestamp = float(decoded["ts_source_seconds"])
        if source_start is None or timestamp < source_start[0]:
            source_start = (timestamp, decoded["ts_source"])
        if source_end is None or timestamp > source_end[0]:
            source_end = (timestamp, decoded["ts_source"])
        batch.append(
            {
                "vehicle_id": vehicle_id,
                "trip_id": trip_id,
                **decoded,
                "ts_replay": None,
                "ts_replay_ns": None,
                "source_dataset": "comma2k19",
                "source_file": f"{source_prefix}/processed_log/CAN/raw_can/data",
            }
        )
        report["raw_frames_decoded"] += 1
        if len(batch) >= 20_000:
            report["canonical_rows"] += insert_measurements(connection, batch)
            batch.clear()
    if batch:
        report["canonical_rows"] += insert_measurements(connection, batch)
        batch.clear()

    speed_times = _read_scalar(segment / "processed_log/CAN/speed/t")
    speed_array = read_npy(segment / "processed_log/CAN/speed/value")
    if len(speed_array.shape) == 1:
        speed_values = [float(v) for v in speed_array.values]
    elif len(speed_array.shape) == 2 and speed_array.shape[1] == 1:
        speed_values = [float(v) for v in speed_array.values]
    else:
        raise ValueError("unexpected comma2k19 processed speed array shape")
    if len(speed_times) != len(speed_values):
        raise ValueError("comma2k19 processed speed time/value lengths differ")
    speed_spec = catalogue["signals"]["vehicle.speed"]
    speed_mapping = next(
        mapping
        for mapping in speed_spec["source_mappings"]
        if mapping["dataset"] == "comma2k19"
    )
    speed_file = f"{source_prefix}/processed_log/CAN/speed/value"
    speed_rows = []
    for row_index, (timestamp, value) in enumerate(zip(speed_times, speed_values), 1):
        token = repr(value)
        speed_rows.append(
            {
                "vehicle_id": vehicle_id,
                "trip_id": trip_id,
                "signal": "vehicle.speed",
                "unit": speed_spec["unit"],
                "ts_source": repr(timestamp),
                "ts_source_seconds": timestamp,
                "ts_replay": None,
                "ts_replay_ns": None,
                "timestamp_basis": "device_boot_seconds; wall-clock segment alignment unavailable",
                "value": value,
                "quality_flag": "ok",
                "source_dataset": "comma2k19",
                "source_file": speed_file,
                "source_row": row_index,
                "source_field": "processed_log/CAN/speed/value",
                "source_unit": speed_mapping["source_unit"],
                "source_value": token,
            }
        )
        if len(speed_rows) >= 20_000:
            report["canonical_rows"] += insert_measurements(connection, speed_rows)
            speed_rows.clear()
    if speed_rows:
        report["canonical_rows"] += insert_measurements(connection, speed_rows)
    report["processed_speed_rows"] = len(speed_times)

    if source_start and source_end:
        update_trip_bounds(
            connection,
            vehicle_id,
            trip_id,
            source_start[1],
            source_end[1],
            None,
            None,
        )
    connection.commit()
    return report
