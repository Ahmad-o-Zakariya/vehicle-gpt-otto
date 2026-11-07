import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vehicle_gpt.adapters.can.adapter import (
    CANONICAL_WHEELS,
    DB,
    MESSAGE_IDS,
    decode_frame,
    replay_virtual,
    steering_frame,
    wheel_speed_frame,
)
from vehicle_gpt.adapters.qnx_logs.parser import parse_slog2info_line
from vehicle_gpt.adapters.vhal.simulator import DEFINITIONS, VhalSimulator
from vehicle_gpt.engines.comparisons import ComparisonEngine
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository
from vehicle_gpt.runtime.messages import Protocol, Provenance, SignalSample
from vehicle_gpt.runtime.storage import RuntimeStore

WHEELS = [
    "vehicle.wheel_speed_fr",
    "vehicle.wheel_speed_fl",
    "vehicle.wheel_speed_rr",
    "vehicle.wheel_speed_rl",
]


def samples(raw):
    mps = (raw * 0.01 - 67.67) / 3.6
    return [
        SignalSample(
            vehicle_id="test:r4",
            trip_id="trip-1",
            protocol=Protocol.CAN,
            source_dataset="comma2k19",
            source_timestamp="10.0",
            replay_timestamp="2018-01-01T00:00:10",
            provenance=Provenance.REAL,
            signal=s,
            value=mps,
            unit="m/s",
        )
        for s in WHEELS
    ]


@given(st.integers(min_value=6767, max_value=65535))
def test_can_dbc_roundtrip_and_virtual_transport(raw):
    frame = wheel_speed_frame(samples(raw))
    received = replay_virtual(frame, channel=f"test-{raw}")
    assert received.data == frame.frame.data
    decoded = decode_frame(frame)
    assert [d.signal for d in decoded] == WHEELS
    for actual, expected in zip(decoded, samples(raw)):
        assert abs(float(actual.value) - float(expected.value)) <= 0.001389
        assert (
            actual.vehicle_id,
            actual.trip_id,
            actual.source_timestamp,
            actual.replay_timestamp,
            actual.provenance,
        ) == ("test:r4", "trip-1", "10.0", "2018-01-01T00:00:10", Provenance.REAL)


def test_can_rejects_missing_wrong_unit_and_invalid_frame():
    rows = samples(30000)
    with pytest.raises(ValueError):
        wheel_speed_frame(rows[:3])
    with pytest.raises(ValueError):
        wheel_speed_frame([r.model_copy(update={"value": -0.1}) for r in rows])
    with pytest.raises(ValueError):
        wheel_speed_frame([r.model_copy(update={"unit": "km/h"}) for r in rows])
    encoded = wheel_speed_frame(rows)
    encoded.frame.dlc = 7
    with pytest.raises(ValueError):
        decode_frame(encoded)


@given(
    st.integers(min_value=-2048, max_value=2047), st.integers(min_value=-8, max_value=7)
)
def test_can_signed_steering_roundtrip(whole, fraction):
    angle = whole * 1.5 + fraction * 0.1
    sample = SignalSample(
        vehicle_id="v",
        trip_id="t",
        protocol=Protocol.CAN,
        source_timestamp="1",
        provenance=Provenance.REAL,
        signal="vehicle.steering_angle",
        value=angle,
        unit="deg",
    )
    frame = steering_frame(sample)
    decoded = decode_frame(frame)[0]
    assert abs(decoded.value - angle) <= 0.051


def test_project_dbc_matches_sampled_real_comma2k19_frames():
    from vehicle_gpt.ingest.comma2k19 import (
        decode_steering,
        decode_wheel_speeds,
        read_npy,
    )

    segment = (
        Path(__file__).resolve().parents[1]
        / "DATASET/comma2k19-master/Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40"
    )
    raw = segment / "processed_log/CAN/raw_can"
    ids = read_npy(raw / "address").values
    payloads = read_npy(raw / "data").values
    comparisons = 0
    for address, payload in zip(ids, payloads):
        can_id = int(address) & 0x7FF
        payload = bytes(payload)
        if can_id == MESSAGE_IDS["steering"]:
            decoded = DB.get_message_by_frame_id(can_id).decode(payload)
            assert (
                abs(
                    decoded["STEER_ANGLE"]
                    + decoded["STEER_FRACTION"]
                    - decode_steering(payload)
                )
                < 1e-9
            )
            comparisons += 1
        elif can_id == MESSAGE_IDS["wheel_speeds"]:
            decoded = DB.get_message_by_frame_id(can_id).decode(payload)
            expected = decode_wheel_speeds(payload)
            for dbc_name, canonical in CANONICAL_WHEELS.items():
                assert abs(decoded[dbc_name] / 3.6 - expected[canonical]) < 1e-9
            comparisons += 1
        if comparisons >= 100:
            break
    assert comparisons == 100


def test_qnx_documented_five_column_parser_preserves_fields():
    event = parse_slog2info_line(
        "Dec 21 21:12:00.029   server_monitor.4104   events*       0                    200 pulses in private pulse pool",
        vehicle_id="v1",
        provenance=Provenance.SYNTHETIC,
    )
    assert event.source_timestamp == "Dec 21 21:12:00.029"
    assert (event.buffer_set, event.buffer_name, event.event_code, event.message) == (
        "server_monitor.4104",
        "events",
        "0",
        "200 pulses in private pulse pool",
    )
    assert event.component == "server_monitor" and event.severity is None
    assert event.timestamp_components == {
        "month": 12,
        "day": 21,
        "hour": 21,
        "minute": 12,
        "second": 0,
        "microsecond": 29000,
    }
    parsed = parse_slog2info_line(
        "Dec 21 21:12:00.029   server_monitor.4104   events       0   message",
        year=2024,
    )
    assert parsed.timestamp_year == 2024 and parsed.source_timestamp.startswith(
        "2024-12-21T21:12:00.029"
    )
    assert event.provenance == Provenance.SYNTHETIC and event.unknown_fields == [
        "buffer_oldest_marker"
    ]
    with pytest.raises(ValueError):
        parse_slog2info_line("bad line")


def test_vhal_uses_aosp_property_ids_and_tracks_invalid_state():
    assert DEFINITIONS["PERF_VEHICLE_SPEED"].property_id == 0x11600207
    assert DEFINITIONS["PERF_ODOMETER"].property_id == 0x11600204
    sim = VhalSimulator("v1")
    msg = sim.update("PERF_VEHICLE_SPEED", 12.5, timestamp_ns=123)
    assert (
        msg.property_id == 0x11600207
        and msg.unit == "m/s"
        and msg.source_timestamp == "123"
    )
    unavailable = sim.update(
        "PERF_ODOMETER", None, status="unavailable", timestamp_ns=124
    )
    assert (
        unavailable.status == "unavailable"
        and unavailable.quality_flag.value == "unavailable"
    )
    with pytest.raises(KeyError):
        sim.update("INVENTED_PROPERTY", 1)


def test_runtime_store_separate_from_frozen_data(tmp_path):
    record = samples(40000)[0]
    store = RuntimeStore(tmp_path / "runtime.sqlite")
    store.append(record)
    assert store.count() == 1
    with pytest.raises(ValueError):
        RuntimeStore(Path("data/processed/runtime.sqlite"))


def test_operational_repository_rejects_ground_truth_path(tmp_path):
    with pytest.raises(ValueError):
        VehicleRepository(tmp_path / "ground_truth" / "ground_truth.sqlite")


def test_bounded_unix_jsonl_bridge_roundtrip(tmp_path):
    import json

    from vehicle_gpt.adapters.someip.bridge import JsonLineVehicleBridge

    async def run():
        socket_path = str(tmp_path / "bridge.sock")
        bridge = JsonLineVehicleBridge(
            lambda req: {"echo": req["params"]}, max_line_bytes=2048
        )
        server = await asyncio.start_unix_server(bridge.handle, path=socket_path)
        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            writer.write(
                json.dumps(
                    {
                        "method": "get",
                        "params": {"signal": "vehicle.speed"},
                        "request_id": "r1",
                    }
                ).encode()
                + b"\n"
            )
            await writer.drain()
            response = json.loads(await reader.readline())
            assert response == {
                "request_id": "r1",
                "result": {"echo": {"signal": "vehicle.speed"}},
            }
            writer.write(b"{not json}\n")
            await writer.drain()
            malformed = json.loads(await reader.readline())
            assert malformed["error"]["code"] == "invalid_request"
            writer.close()
            await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_city_highway_comparison_fails_closed():
    result = ComparisonEngine().run(
        query_id="test",
        vehicle_id="ved:455",
        signal="vehicle.speed",
        trip_groups={"city": [], "highway": []},
        operating_labels={"city": "city", "highway": "highway"},
    )
    assert result.coverage.status == "unavailable"
    assert result.error_code == "unsupported_comparison"


def test_energy_throughput_comparison_uses_gross_energy_and_absolute_delta():
    repo = VehicleRepository(
        Path(__file__).resolve().parents[1] / "data/processed/vehicle_gpt.sqlite"
    )
    voltage = repo.samples("ved:455", "battery.voltage", limit=100_000)
    trips = sorted({row["trip_id"] for row in voltage if row["trip_id"]})
    result = ComparisonEngine().run(
        query_id="energy-test",
        vehicle_id="ved:455",
        signal="battery.voltage",
        trip_groups={"first": trips[:1], "second": trips[1:2]},
        min_samples=1,
        metric="energy_throughput",
    )
    assert result.coverage.status == "adequate"
    assert result.result["absolute_difference"] >= 0
    assert "gross absolute battery energy throughput" in result.units["group_mean"]
