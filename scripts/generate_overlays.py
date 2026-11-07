#!/usr/bin/env python3
"""Generate deterministic synthetic overlay events and isolated evaluation labels."""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from vehicle_gpt.storage.database import initialize_database, load_catalogue, naive_datetime_ns

MAIN_DB = ROOT / "data/processed/vehicle_gpt.sqlite"
GROUND_TRUTH_DB = ROOT / "data/processed/ground_truth/ground_truth.sqlite"
GROUND_TRUTH_JSON = ROOT / "data/processed/ground_truth/injections.json"
DERIVED_HASH_MANIFEST = ROOT / "data/manifests/derived_output_hashes.json"
CONFIG = ROOT / "configs/injections.yaml"
SPLITS = ROOT / "configs/splits.yaml"


def _parse_replay(token: str) -> datetime:
    return datetime.fromisoformat(token.replace("Z", "+00:00")).replace(tzinfo=None)


def _sample_at(connection, vehicle: str, trip: str, signal: str, seconds: float):
    row = connection.execute(
        """SELECT ts_source,ts_replay,ts_replay_ns,ts_source_seconds,value,unit
           FROM canonical_measurement WHERE vehicle_id=? AND trip_id=? AND signal=?
           AND ts_source_seconds BETWEEN ? AND ?
           ORDER BY ABS(ts_source_seconds-?) LIMIT 1""",
        (vehicle, trip, signal, seconds - 0.06, seconds + 0.06, seconds),
    ).fetchone()
    if row is None:
        raise ValueError(f"no source sample near {vehicle}/{trip}/{signal} t={seconds}")
    return row


def _thermal_ramp_value(
    source_baseline: float | None,
    source_t0_baseline: float,
    offset_seconds: float,
    ramp_seconds: float,
    rise_c: float,
) -> float:
    """Add a linear synthetic rise to each source sample; missing points use source T0."""
    if ramp_seconds <= 0 or not -ramp_seconds <= offset_seconds <= 0:
        raise ValueError("thermal ramp offset must lie within a positive pre-warning ramp")
    baseline = source_t0_baseline if source_baseline is None else source_baseline
    fraction = (offset_seconds + ramp_seconds) / ramp_seconds
    return round(float(baseline) + float(rise_c) * fraction, 3)


def _freeze_frame_metadata(source_values: dict, injected_values: dict) -> dict:
    return {
        "synthetic": True,
        "captured_source_values": source_values,
        "captured_source_values_provenance": "real_source_snapshot_at_T0",
        "synthetic_injected_values_at_T0": injected_values,
        "timestamp_offset_seconds": 0,
    }


def _insert_event(connection, event_id, vehicle, trip, event_type, source_time,
                  replay_time, replay_ns, injection_id, metadata):
    connection.execute(
        """INSERT INTO overlay_event(event_id,vehicle_id,trip_id,event_type,ts_source,
           ts_replay,ts_replay_ns,provenance,injection_id,event_metadata_json)
           VALUES (?,?,?,?,?,?,?,'synthetic',?,?)""",
        (event_id, vehicle, trip, event_type, source_time, replay_time, replay_ns,
         injection_id, json.dumps(metadata, sort_keys=True, separators=(",", ":"))),
    )


def _add_sample(connection, gt, event_id, injection_id, vehicle, trip, signal, unit,
                source_second, replay_start, injected, quality="synthetic_injected"):
    original = None
    if signal in ("battery.temperature", "thermal.coolant_temperature_inlet"):
        real = _sample_at(connection, vehicle, trip, signal, source_second)
        original = real[4]
        replay_ns = int(real[2])
        source_time = real[0]
        replay_time = real[1]
    else:
        replay = replay_start + timedelta(seconds=source_second)
        replay_ns = naive_datetime_ns(replay)
        source_time = f"source_seconds={source_second:.1f}"
        replay_time = replay.isoformat(timespec="microseconds")
    connection.execute(
        """INSERT INTO overlay_sample(event_id,signal,unit,ts_replay_ns,value,
           quality_flag,injection_id,provenance) VALUES (?,?,?,?,?,?,?,'synthetic')""",
        (event_id, signal, unit, replay_ns, injected, quality, injection_id),
    )
    gt.append({
        "signal": signal, "source_seconds": round(source_second, 3),
        "ts_source": source_time, "ts_replay": replay_time, "ts_replay_ns": replay_ns,
        "original_value": original, "injected_value": injected, "unit": unit,
        "quality_flag": quality,
    })


def _add_injection(connection, sidecar, record):
    sidecar.execute(
        """INSERT INTO injection(injection_id,vehicle_id,trip_id,event_type,ts_replay_ns,
           random_seed,parameters_json,expected_label,split,overlay_event_ids_json,
           created_by_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record["injection_id"], record["vehicle_id"], record["trip_id"],
            record["event_type"], record["ts_replay_ns"], record["random_seed"],
            json.dumps(record["parameters"], sort_keys=True), record["expected_label"],
            record["split"], json.dumps(record["overlay_event_ids"], sort_keys=True),
            "vehicle-gpt-dataset/0.1.0",
        ),
    )
    for item in record.get("signals", []):
        sidecar.execute(
            """INSERT INTO injection_signal(injection_id,signal,ts_replay_ns,
               original_value,injected_value,unit) VALUES (?,?,?,?,?,?)""",
            (record["injection_id"], item["signal"], item["ts_replay_ns"],
             item["original_value"], item["injected_value"], item["unit"]),
        )


def generate() -> dict[str, object]:
    if not MAIN_DB.exists():
        raise FileNotFoundError(MAIN_DB)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    split_config_hash = config_hash
    if GROUND_TRUTH_DB.exists():
        GROUND_TRUTH_DB.unlink()
    GROUND_TRUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    sidecar = sqlite3.connect(GROUND_TRUTH_DB)
    sidecar.execute("PRAGMA foreign_keys=ON")
    sidecar.executescript((ROOT / "src/vehicle_gpt/ground_truth/schema.sql").read_text())
    connection = initialize_database(MAIN_DB, load_catalogue())
    connection.execute("PRAGMA foreign_keys=ON")
    for table in ("event_window", "derived_1hz", "trip_rollup", "deviation_flag"):
        connection.execute(f"DELETE FROM {table}")
    connection.execute("DELETE FROM overlay_sample WHERE provenance='synthetic'")
    connection.execute("DELETE FROM overlay_event WHERE provenance='synthetic'")

    records = []
    controls = []
    split_rows = []
    all_signals = []
    rng = random.Random(int(config["seed"]))
    thermal = config["thermal"]
    vehicle = thermal["vehicle_id"]
    for index, trip in enumerate(thermal["trip_ids"], start=1):
        trip_row = connection.execute(
            "SELECT ts_replay_start FROM trip_registry WHERE vehicle_id=? AND trip_id=?",
            (vehicle, trip),
        ).fetchone()
        if not trip_row or not trip_row[0]:
            raise ValueError(f"trip is missing replay dates: {trip}")
        replay_start = _parse_replay(trip_row[0])
        low, high = thermal["event_offset_seconds_range"]
        t0 = rng.randint(int(low), int(high))
        t0_sample = _sample_at(connection, vehicle, trip, "battery.temperature", t0)
        t0_ns = int(t0_sample[2])
        held_out = trip == thermal["held_out_trip_id"]
        injection_id = f"inj:thermal:{trip.lower()}"
        split = "held_out_test" if held_out else "train_development"
        family = "thermal_overheat_target_variant" if held_out else "thermal_overheat_recurrence"
        event_ids = []
        gt_signals = []

        pump_id = f"{injection_id}:pump"
        temp_id = f"{injection_id}:temperature"
        dropout_id = f"{injection_id}:dropout"
        distractor_id = f"{injection_id}:distractor"
        warning_id = f"{injection_id}:warning"
        dtc_id = f"{injection_id}:dtc"
        freeze_id = f"{injection_id}:freeze-frame"
        qnx_id = f"{injection_id}:qnx"
        source_t0 = t0_sample[0]
        replay_t0 = t0_sample[1]
        for eid, kind, metadata in (
            (pump_id, "thermal.coolant_pump_duty_drop", {"synthetic": True, "pump_signal_present_in_source": False}),
            (temp_id, "thermal.battery_temperature_ramp", {"synthetic": True, "baseline_signal": "battery.temperature", "rise_c": thermal["battery_temperature_rise_c"]}),
            (dropout_id, "thermal.coolant_inlet_sensor_dropout", {"synthetic": True, "signal": "thermal.coolant_temperature_inlet"}),
            (distractor_id, "scenario.unrelated_distractor_change", {"synthetic": True, "signal": "scenario.distractor_load"}),
        ):
            event_ids.append(eid)
            _insert_event(connection, eid, vehicle, trip, kind, source_t0, replay_t0, t0_ns, injection_id, metadata)

        period_ticks = max(1, round(float(thermal["sample_period_seconds"]) * 10))
        ramp = int(thermal["ramp_duration_seconds"])
        for tick in range(0, ramp * 10 + 1, period_ticks):
            offset = -ramp + tick / 10.0
            second = t0 + offset
            real = _sample_at(connection, vehicle, trip, "battery.temperature", second)
            injected = _thermal_ramp_value(
                real[4],
                float(t0_sample[4]),
                offset,
                ramp,
                float(thermal["battery_temperature_rise_c"]),
            )
            _add_sample(connection, gt_signals, temp_id, injection_id, vehicle, trip,
                        "battery.temperature", "degC", second, replay_start, injected)

        drop_start = int(thermal["pump_drop_start_seconds_before_t0"])
        pump_initial = float(thermal["pump_duty_initial_percent"])
        pump_final = float(thermal["pump_duty_drop_percent"])
        for tick in range(0, drop_start * 10 + 1, period_ticks):
            offset = -drop_start + tick / 10.0
            frac = min(1.0, max(0.0, (offset + drop_start) / max(1, drop_start - 30)))
            duty = round(pump_initial + (pump_final - pump_initial) * frac, 2)
            _add_sample(connection, gt_signals, pump_id, injection_id, vehicle, trip,
                        "thermal.coolant_pump_duty", "percent", t0 + offset,
                        replay_start, duty)

        dropout_start = int(thermal["dropout_seconds_before_t0"])
        dropout_end = int(thermal["dropout_seconds_after_t0"])
        for tick in range(0, (dropout_start + dropout_end) * 10 + 1, period_ticks):
            offset = -dropout_start + tick / 10.0
            _add_sample(connection, gt_signals, dropout_id, injection_id, vehicle, trip,
                        "thermal.coolant_temperature_inlet", "degC", t0 + offset,
                        replay_start, None, "synthetic_sensor_dropout")

        distractor_start = -int(thermal["distractor_start_seconds_before_t0"])
        for offset in range(distractor_start, -29, 1):
            _add_sample(connection, gt_signals, distractor_id, injection_id, vehicle, trip,
                        "scenario.distractor_load", "arbitrary_unit", t0 + offset,
                        replay_start, float(thermal["distractor_value"]))

        event_ids.append(warning_id)
        _insert_event(connection, warning_id, vehicle, trip, "diagnostic.warning",
                      source_t0, replay_t0, t0_ns, injection_id,
                      {"code": "BATT_OVERTEMP", "synthetic": True, "label": "warning_at_T0"})
        event_ids.append(dtc_id)
        _insert_event(connection, dtc_id, vehicle, trip, "diagnostic.dtc",
                      source_t0, replay_t0, t0_ns, injection_id,
                      {"code": "DTC_SYNTH_BATT_OVERTEMP", "synthetic": True, "standardized_oem_code": False})
        freeze_values = {}
        synthetic_t0_values = {}
        for signal in ("battery.temperature", "battery.soc", "thermal.coolant_temperature_inlet"):
            freeze_values[signal] = _sample_at(connection, vehicle, trip, signal, t0)[4]
            injected = connection.execute(
                """SELECT value FROM overlay_sample WHERE injection_id=? AND signal=?
                   AND ts_replay_ns=? ORDER BY overlay_sample_id LIMIT 1""",
                (injection_id, signal, t0_ns),
            ).fetchone()
            if injected is not None:
                synthetic_t0_values[signal] = injected[0]
        event_ids.append(freeze_id)
        _insert_event(connection, freeze_id, vehicle, trip, "diagnostic.freeze_frame",
                      source_t0, replay_t0, t0_ns, injection_id,
                      _freeze_frame_metadata(freeze_values, synthetic_t0_values))
        event_ids.append(qnx_id)
        _insert_event(connection, qnx_id, vehicle, trip, "diagnostic.qnx_log_line",
                      source_t0, replay_t0, t0_ns, injection_id,
                      {"synthetic": True, "line": f"vehicle-bms[synthetic]: BATT_OVERTEMP warning at {replay_t0}"})

        record = {
            "injection_id": injection_id, "vehicle_id": vehicle, "trip_id": trip,
            "event_type": "thermal_overtemperature", "ts_replay_ns": t0_ns,
            "random_seed": int(config["seed"]), "split": split,
            "expected_label": "synthetic recurrent overheating pattern; temporal ordering is not causal evidence",
            "parameters": {"config_sha256": config_hash, "config": thermal,
                           "t0_source_seconds": t0, "held_out_target": held_out},
            "overlay_event_ids": event_ids, "signals": gt_signals,
        }
        _add_injection(connection, sidecar, record)
        records.append(record)
        split_rows.append({"injection_id": injection_id, "split": split, "pattern_family": family, "seed": int(config["seed"])})
        all_signals.extend({"injection_id": injection_id, **item} for item in gt_signals)

    for trip in thermal.get("control_trip_ids", []):
        row = connection.execute(
            "SELECT ts_replay_start,ts_replay_end FROM trip_registry WHERE vehicle_id=? AND trip_id=?",
            (vehicle, trip),
        ).fetchone()
        if not row or not row[0] or not row[1]:
            raise ValueError(f"control trip is missing measured date bounds: {trip}")
        has_temperature = connection.execute(
            "SELECT 1 FROM canonical_measurement WHERE vehicle_id=? AND trip_id=? AND signal='battery.temperature' LIMIT 1",
            (vehicle, trip),
        ).fetchone()
        if not has_temperature:
            raise ValueError(f"control trip lacks the measured battery temperature signal: {trip}")
        controls.append({
            "vehicle_id": vehicle, "trip_id": trip,
            "ts_replay_start": row[0], "ts_replay_end": row[1],
            "status": "untouched real measurement control; no synthetic overlay applied",
        })

    # One held-out synthetic disengagement with an explicit reason; local OpenLKA has no reason field.
    open_trip = connection.execute(
        """SELECT vehicle_id,trip_id,ts_replay_start FROM trip_registry
           WHERE source_dataset='openlka' AND ts_replay_start IS NOT NULL
           ORDER BY vehicle_id LIMIT 1"""
    ).fetchone()
    if open_trip:
        open_vehicle, open_trip_id, open_start_token = open_trip
        open_start = _parse_replay(open_start_token)
        open_sample = connection.execute(
            """SELECT ts_source,ts_replay,ts_replay_ns,ts_source_seconds FROM canonical_measurement
               WHERE vehicle_id=? AND trip_id=? AND signal='adas.lateral_control_enabled'
               ORDER BY ts_source_seconds LIMIT 1""",
            (open_vehicle, open_trip_id),
        ).fetchone()
        if open_sample:
            second = float(open_sample[3]) + 25.0
            sample = _sample_at(connection, open_vehicle, open_trip_id,
                                "adas.lateral_control_enabled", second)
            injection_id = "inj:adas:heldout_camera_occlusion"
            event_id = f"{injection_id}:event"
            _insert_event(connection, event_id, open_vehicle, open_trip_id,
                          "adas.synthetic_disengagement", sample[0], sample[1], int(sample[2]),
                          injection_id,
                          {"synthetic": True, "reason_code": config["adas"]["reason_code"],
                           "description": config["adas"]["description"]})
            record = {
                "injection_id": injection_id, "vehicle_id": open_vehicle,
                "trip_id": open_trip_id, "event_type": "adas_disengagement",
                "ts_replay_ns": int(sample[2]), "random_seed": int(config["seed"]),
                "split": "held_out_test", "expected_label": "synthetic disengagement; reason code is injected",
                "parameters": {"config_sha256": config_hash, **config["adas"]},
                "overlay_event_ids": [event_id], "signals": [],
            }
            _add_injection(connection, sidecar, record)
            records.append(record)
            split_rows.append({"injection_id": injection_id, "split": "held_out_test", "pattern_family": "adas_disengagement_reason", "seed": int(config["seed"])})

    connection.commit()
    DERIVED_HASH_MANIFEST.unlink(missing_ok=True)
    sidecar.executemany(
        "INSERT INTO split_manifest(injection_id,split,pattern_family,seed,config_sha256) VALUES (?,?,?,?,?)",
        [(r["injection_id"], r["split"], r["pattern_family"], r["seed"], split_config_hash) for r in split_rows],
    )
    sidecar.commit()
    connection.close()
    sidecar.close()

    split_doc = {
        "seed": int(config["seed"]), "unit": "injection_pattern",
        "train_development": [r["injection_id"] for r in split_rows if r["split"] == "train_development"],
        "held_out_test": [r["injection_id"] for r in split_rows if r["split"] == "held_out_test"],
        "pattern_families": {r["injection_id"]: r["pattern_family"] for r in split_rows},
        "config_sha256": split_config_hash,
        "status": "generated; held-out target and ADAS reason family excluded from development",
    }
    SPLITS.write_text(yaml.safe_dump(split_doc, sort_keys=False), encoding="utf-8")
    log = {
        "seed": int(config["seed"]), "generator_version": "thermal-overlay-v1",
        "software": {"python": platform.python_version(), "pyyaml": yaml.__version__},
        "config_sha256": config_hash, "splits_config_sha256": split_config_hash,
        "injections": records, "untouched_controls": controls,
    }
    GROUND_TRUTH_JSON.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"injections": len(records), "training_development": len(split_doc["train_development"]),
            "held_out_test": len(split_doc["held_out_test"]),
            "overlay_events": sum(len(r["overlay_event_ids"]) for r in records),
            "overlay_samples": len(all_signals), "config_sha256": config_hash}


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
