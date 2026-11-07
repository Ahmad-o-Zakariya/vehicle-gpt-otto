from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import can
import cantools

from vehicle_gpt.runtime.messages import Protocol, Provenance, QualityFlag, SignalSample

DBC_PATH = Path(__file__).resolve().parents[4] / "configs/verified_comma2k19.dbc"
DB = cantools.database.load_file(DBC_PATH)
MESSAGE_IDS = {"steering": 37, "wheel_speeds": 170}
CANONICAL_WHEELS = {
    "WHEEL_SPEED_FR": "vehicle.wheel_speed_fr",
    "WHEEL_SPEED_FL": "vehicle.wheel_speed_fl",
    "WHEEL_SPEED_RR": "vehicle.wheel_speed_rr",
    "WHEEL_SPEED_RL": "vehicle.wheel_speed_rl",
}


@dataclass(frozen=True)
class ReplayFrame:
    frame: can.Message
    vehicle_id: str
    trip_id: str
    source_timestamp: str
    replay_timestamp: str | None
    signal_names: tuple[str, ...]
    units: tuple[str, ...]
    quality_flag: QualityFlag
    provenance: Provenance


def _timestamp_order(samples: Iterable[SignalSample]) -> list[SignalSample]:
    rows = list(samples)
    keys = [s.source_timestamp for s in rows]
    if keys != sorted(keys):
        raise ValueError("CAN replay samples must be ordered by source_timestamp")
    return rows


def wheel_speed_frame(samples: list[SignalSample]) -> ReplayFrame:
    """Encode a four-wheel sample using only the verified 0x0AA layout."""
    if len(samples) != 4:
        raise ValueError("wheel speed frame requires exactly four wheel signals")
    by_signal = {s.signal: s for s in samples}
    if set(by_signal) != set(CANONICAL_WHEELS.values()):
        raise ValueError("wheel speed signals must be the four verified RAV4 channels")
    ref = samples[0]
    for s in samples:
        if s.value is None or s.quality_flag != QualityFlag.OK:
            raise ValueError(f"cannot encode missing or flagged signal {s.signal}")
        if s.unit != "m/s" or (
            s.vehicle_id,
            s.trip_id,
            s.source_timestamp,
            s.replay_timestamp,
        ) != (ref.vehicle_id, ref.trip_id, ref.source_timestamp, ref.replay_timestamp):
            raise ValueError(
                "frame samples must share identity, timestamps, and canonical m/s units"
            )
    values = {}
    for dbc_name, canonical in CANONICAL_WHEELS.items():
        mps = float(by_signal[canonical].value)
        if mps < 0:
            raise ValueError(
                f"negative wheel speed is outside the configured plausible range: {mps} m/s"
            )
        kmh = mps * 3.6
        raw = round((kmh + 67.67) / 0.01)
        if not 0 <= raw <= 65535:
            raise ValueError(f"wheel speed outside representable DBC range: {mps} m/s")
        values[dbc_name] = raw * 0.01 - 67.67
    msg = DB.get_message_by_frame_id(MESSAGE_IDS["wheel_speeds"])
    payload = msg.encode(values, scaling=True, strict=True)
    frame = can.Message(
        arbitration_id=msg.frame_id, data=payload, is_extended_id=False, check=True
    )
    return ReplayFrame(
        frame,
        ref.vehicle_id,
        ref.trip_id,
        ref.source_timestamp,
        ref.replay_timestamp,
        tuple(CANONICAL_WHEELS.values()),
        tuple("m/s" for _ in range(4)),
        ref.quality_flag,
        ref.provenance,
    )


def steering_frame(sample: SignalSample) -> ReplayFrame:
    """Encode a verified signed Motorola steering value with 0.1-degree quantization."""
    if (
        sample.signal != "vehicle.steering_angle"
        or sample.unit != "deg"
        or sample.value is None
    ):
        raise ValueError("expected a non-missing vehicle.steering_angle in degrees")
    if sample.quality_flag != QualityFlag.OK:
        raise ValueError("cannot encode a quality-flagged steering value")
    angle = float(sample.value)
    candidates = []
    for coarse in range(round(angle / 1.5) - 2, round(angle / 1.5) + 3):
        fine = round((angle - coarse * 1.5) / 0.1)
        if -2048 <= coarse <= 2047 and -8 <= fine <= 7:
            error = abs(angle - (coarse * 1.5 + fine * 0.1))
            if error <= 0.051:
                candidates.append((error, coarse, fine))
    if not candidates:
        raise ValueError("steering angle is outside the signed DBC representation")
    _, whole, fraction = min(candidates)
    msg = DB.get_message_by_frame_id(MESSAGE_IDS["steering"])
    payload = msg.encode(
        {"STEER_ANGLE": whole * 1.5, "STEER_FRACTION": fraction * 0.1},
        scaling=True,
        strict=True,
    )
    frame = can.Message(
        arbitration_id=msg.frame_id, data=payload, is_extended_id=False, check=True
    )
    return ReplayFrame(
        frame,
        sample.vehicle_id,
        sample.trip_id or "",
        sample.source_timestamp,
        sample.replay_timestamp,
        (sample.signal,),
        (sample.unit,),
        sample.quality_flag,
        sample.provenance,
    )


def decode_frame(row: ReplayFrame) -> list[SignalSample]:
    msg = DB.get_message_by_frame_id(row.frame.arbitration_id)
    if (
        row.frame.is_error_frame
        or row.frame.is_remote_frame
        or row.frame.dlc != msg.length
    ):
        raise ValueError("invalid CAN frame type or message length")
    decoded = msg.decode(row.frame.data, decode_choices=False, scaling=True)
    if msg.frame_id == MESSAGE_IDS["wheel_speeds"]:
        result = []
        for dbc_name, canonical in CANONICAL_WHEELS.items():
            value = float(decoded[dbc_name]) / 3.6
            result.append(
                SignalSample(
                    vehicle_id=row.vehicle_id,
                    trip_id=row.trip_id,
                    protocol=Protocol.CAN,
                    source_dataset="comma2k19",
                    source_timestamp=row.source_timestamp,
                    replay_timestamp=row.replay_timestamp,
                    provenance=row.provenance,
                    quality_flag=row.quality_flag,
                    signal=canonical,
                    value=value,
                    unit="m/s",
                )
            )
        return result
    if msg.frame_id == MESSAGE_IDS["steering"]:
        value = float(decoded["STEER_ANGLE"]) + float(decoded["STEER_FRACTION"])
        return [
            SignalSample(
                vehicle_id=row.vehicle_id,
                trip_id=row.trip_id,
                protocol=Protocol.CAN,
                source_dataset="comma2k19",
                source_timestamp=row.source_timestamp,
                replay_timestamp=row.replay_timestamp,
                provenance=row.provenance,
                quality_flag=row.quality_flag,
                signal="vehicle.steering_angle",
                value=value,
                unit="deg",
            )
        ]
    raise ValueError(f"unregistered CAN frame ID: 0x{row.frame.arbitration_id:x}")


def replay_virtual(row: ReplayFrame, channel: str = "vehicle-gpt-test") -> can.Message:
    """Clearly labelled python-can virtual transport; this is not SocketCAN."""
    with (
        can.Bus(interface="virtual", channel=channel) as sender,
        can.Bus(interface="virtual", channel=channel) as receiver,
    ):
        sender.send(row.frame)
        received = receiver.recv(timeout=1.0)
    if received is None:
        raise TimeoutError("no frame received on python-can virtual transport")
    if (
        received.arbitration_id != row.frame.arbitration_id
        or received.data != row.frame.data
    ):
        raise ValueError("CAN transport changed frame contents")
    return received


def socketcan_available(channel: str = "vcan0") -> bool:
    try:
        with can.Bus(interface="socketcan", channel=channel):
            return True
    except OSError, can.CanError, ValueError:
        return False
