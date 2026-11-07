#!/usr/bin/env python3
"""Create a concise, read-only acceptance audit from the generated release files."""

from __future__ import annotations

import json
import os
import platform
import resource
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_dataset import _dataset_name

DB = ROOT / "data/processed/vehicle_gpt.sqlite"
GT_DB = ROOT / "data/processed/ground_truth/ground_truth.sqlite"
GT_JSON = ROOT / "data/processed/ground_truth/injections.json"
RAW = ROOT / "data/manifests/raw_files.json"
VALIDATION = ROOT / "data/manifests/validation_report.json"
INGESTION = ROOT / "data/manifests/ingestion_report.json"
OUTPUT = ROOT / "data/manifests/acceptance_report.json"


def _rows(connection, sql, args=()):
    return [dict(row) for row in connection.execute(sql, args)]


def _memory_cap():
    path = Path("/sys/fs/cgroup/memory.max")
    if not path.exists():
        return "not available"
    value = path.read_text().strip()
    return "unlimited" if value == "max" else value


def audit():
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    ingestion = json.loads(INGESTION.read_text(encoding="utf-8"))
    gt_log = json.loads(GT_JSON.read_text(encoding="utf-8"))
    splits = yaml.safe_load((ROOT / "configs/splits.yaml").read_text(encoding="utf-8"))
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    gt = sqlite3.connect(GT_DB)
    gt.row_factory = sqlite3.Row
    try:
        source_counts = _rows(connection,
            "SELECT source_dataset,COUNT(*) AS rows,SUM(value IS NULL) AS missing FROM canonical_measurement GROUP BY source_dataset ORDER BY source_dataset")
        vehicle_rows = _rows(connection,
            """SELECT v.vehicle_id,v.source_dataset,v.make,v.model,v.model_year,v.powertrain,
                      COUNT(t.trip_id) AS trips,MIN(t.ts_replay_start) AS first_time,
                      MAX(t.ts_replay_end) AS last_time,
                      (SELECT COUNT(*) FROM vehicle_capability c WHERE c.vehicle_id=v.vehicle_id) AS signal_count
               FROM vehicle_registry v LEFT JOIN trip_registry t USING(vehicle_id)
               GROUP BY v.vehicle_id ORDER BY v.vehicle_id""")
        trip_counts = _rows(connection,
            "SELECT source_dataset,COUNT(*) AS trips,MIN(ts_replay_start) AS first_time,MAX(ts_replay_end) AS last_time FROM trip_registry GROUP BY source_dataset ORDER BY source_dataset")
        file_counts = _rows(connection,
            "SELECT source_dataset,COUNT(*) AS files,SUM(size_bytes) AS bytes FROM dataset_manifest GROUP BY source_dataset ORDER BY source_dataset")
        quality = _rows(connection,
            "SELECT source_dataset,quality_flag,COUNT(*) AS rows,SUM(value IS NULL) AS missing FROM canonical_measurement GROUP BY source_dataset,quality_flag ORDER BY source_dataset,quality_flag")
        invalid = _rows(connection,
            """SELECT source_dataset,signal,COUNT(*) AS rows,MIN(value) AS min_value,MAX(value) AS max_value
               FROM canonical_measurement WHERE quality_flag='out_of_range'
               GROUP BY source_dataset,signal ORDER BY source_dataset,signal""")
        duplicate_times = _rows(connection,
            """SELECT source_dataset,COUNT(*) AS repeated_groups,SUM(n-1) AS extra_rows,MAX(n) AS largest_group
               FROM (SELECT source_dataset,vehicle_id,trip_id,signal,ts_source_seconds,COUNT(*) AS n
                     FROM canonical_measurement GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1)
               GROUP BY source_dataset ORDER BY source_dataset""")
        duplicate_keys = connection.execute(
            """SELECT COUNT(*) FROM (SELECT source_dataset,source_file,source_row,source_field
               FROM canonical_measurement GROUP BY 1,2,3,4 HAVING COUNT(*)>1)""").fetchone()[0]
        tum_signal_trip_coverage = _rows(connection,
            """SELECT sc.signal,COUNT(*) AS trips,SUM(sc.sample_count) AS rows,SUM(sc.missing_count) AS missing
               FROM signal_coverage sc JOIN trip_registry t USING(vehicle_id,trip_id)
               WHERE t.source_dataset='tum_bmw_i3' GROUP BY sc.signal ORDER BY sc.signal""")
        open_transitions = _rows(connection,
            """SELECT json_extract(event_metadata_json,'$.from') AS from_state,
                      json_extract(event_metadata_json,'$.to') AS to_state,COUNT(*) AS events
               FROM overlay_event WHERE provenance='real'
               GROUP BY from_state,to_state ORDER BY from_state,to_state""")
        open_timestamp = _rows(connection,
            """SELECT COUNT(DISTINCT vehicle_id) AS clips,
                      SUM(CASE WHEN ts_replay_start IS NOT NULL THEN 1 ELSE 0 END) AS clips_with_absolute_bounds,
                      MIN(ts_replay_start) AS first_time,MAX(ts_replay_end) AS last_time
               FROM trip_registry WHERE source_dataset='openlka'""")[0]
        event_counts = _rows(connection,
            "SELECT provenance,event_type,COUNT(*) AS events FROM overlay_event GROUP BY provenance,event_type ORDER BY provenance,event_type")
        overlay_sample_count = connection.execute("SELECT COUNT(*) FROM overlay_sample").fetchone()[0]
        capability_invalid = connection.execute(
            """SELECT COUNT(*) FROM vehicle_capability WHERE missing_rate NOT BETWEEN 0 AND 1
               OR (coverage IS NOT NULL AND coverage NOT BETWEEN 0 AND 1)""").fetchone()[0]
        openlka_date_check = {
            "repeated_timestamp_groups": sum(x["repeated_groups"] for x in duplicate_times if x["source_dataset"] == "openlka"),
            "extra_timestamp_rows": sum(x["extra_rows"] for x in duplicate_times if x["source_dataset"] == "openlka"),
        }
        gt_injections = _rows(gt, "SELECT injection_id,vehicle_id,trip_id,event_type,ts_replay_ns,split FROM injection ORDER BY injection_id")
        gt_signal_rows = gt.execute("SELECT COUNT(*) FROM injection_signal").fetchone()[0]
        controls = gt_log.get("untouched_controls", [])
        thermal = []
        for record in gt_log["injections"]:
            if record["event_type"] != "thermal_overtemperature":
                continue
            t0 = float(record["parameters"]["t0_source_seconds"])
            windows = {}
            for item in record["signals"]:
                key = item["signal"]
                windows.setdefault(key, []).append(float(item["source_seconds"]) - t0)
            thermal.append({
                "trip_id": record["trip_id"], "split": record["split"],
                "t0_source_seconds": t0,
                "samples": {name: {"count": len(vals), "offset_start_seconds": min(vals), "offset_end_seconds": max(vals)} for name, vals in sorted(windows.items())},
            })
        table_names = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        main_has_gt = bool({"injection", "injection_signal", "split_manifest"} & table_names)
        source_mapping_counts = dict(connection.execute("SELECT source_dataset,COUNT(*) FROM dataset_manifest GROUP BY source_dataset"))

        checks = [
            {"check": "database_integrity_and_foreign_keys", "verdict": "PASS" if validation.get("sqlite_integrity")=="ok" and validation.get("foreign_key_violations")==0 else "FAIL", "evidence": "SQLite integrity_check and foreign_key_check recorded in validation report."},
            {"check": "raw_checksums_and_file_classification", "verdict": "PASS" if validation.get("raw_checksums_verified")==raw["file_count"] and source_mapping_counts=={"ved":6,"tum_bmw_i3":72,"tum_simulation":48,"comma2k19":61,"openlka":827} else "FAIL", "evidence": {"files": raw["file_count"], "classification": source_mapping_counts}},
            {"check": "canonical_provenance_and_source_keys", "verdict": "PASS" if duplicate_keys==0 else "FAIL", "evidence": {"canonical_real_rows": validation.get("canonical_rows"), "duplicate_source_keys": duplicate_keys}},
            {"check": "overlay_trace_and_ground_truth_isolation", "verdict": "PASS" if not main_has_gt and validation.get("synthetic_overlay_events")==41 and overlay_sample_count==gt_signal_rows else "FAIL", "evidence": {"main_has_ground_truth_tables": main_has_gt, "synthetic_events": validation.get("synthetic_overlay_events"), "overlay_samples": overlay_sample_count, "ground_truth_signal_rows": gt_signal_rows}},
            {"check": "timestamp_order_and_uniqueness", "verdict": "PASS WITH LIMITATIONS", "evidence": {"OpenLKA_unix_time_repeated_groups": openlka_date_check["repeated_timestamp_groups"], "extra_rows_at_repeated_timestamps": openlka_date_check["extra_timestamp_rows"], "interpretation": "source rows remain unique, but OpenLKA unix_time is not unique at sample cadence; absolute event timing must be treated cautiously."}},
            {"check": "quality_and_signal_coverage", "verdict": "PASS WITH LIMITATIONS" if capability_invalid==0 else "FAIL", "evidence": {"out_of_range_records": invalid, "capability_range_errors": capability_invalid, "TUM_trip_signal_coverage": tum_signal_trip_coverage}},
            {"check": "derived_reproducibility", "verdict": "PASS" if validation.get("derived_hashes_match") else "FAIL", "evidence": validation.get("derived_rows")},
            {"check": "python_3_11_compatibility_and_target_hardware", "verdict": "NOT VERIFIED", "evidence": "Local scripts/tests ran under Python 3.14; project declares Python >=3.11,<3.12. No ARM A55 device run. RLIMIT_AS is 2 GiB; RLIMIT_RSS is not enforced."},
            {"check": "redistribution_rights", "verdict": "NOT VERIFIED", "evidence": "TUM reuse terms and comma2k19 dataset-specific rights are unclear; OpenLKA data has separate terms. Internal-only handling pending review."},
        ]

        question_coverage = [
            {"id": 1, "question": "Why has driving range reduced over the last two weeks?", "vehicle": "ved:455 (2013 Nissan Leaf, VehId 455)", "signals": ["vehicle.speed","vehicle.latitude","vehicle.longitude","battery.soc","battery.current","battery.voltage"], "tables": ["canonical_measurement","vehicle_capability","signal_coverage","derived_1hz","trip_rollup"], "coverage": "2017-11-05 to 2018-11-05; 293 trips, 191 active dates; final 14 days contain 10 trips on 7 dates.", "provenance": "real source values; source-derived replay wall times from DayNum.", "limitations": "No direct range or odometer signal; available battery/route values are proxies. Sparse daily use; no current-date data.", "verdict": "PARTIALLY SUPPORTED"},
            {"id": 2, "question": "When did fuel efficiency show its largest drop?", "vehicle": "ved:119 (measured diesel vehicle; model identity incomplete)", "signals": ["vehicle.fuel_rate","vehicle.speed","vehicle.latitude","vehicle.longitude"], "tables": ["canonical_measurement","vehicle_capability","signal_coverage","trip_rollup"], "coverage": "5 trips, 1,822 samples, 5 active dates; 2018-02-25 to 2018-10-26.", "provenance": "real measured fuel rate and speed.", "limitations": "Too few trips for a robust longitudinal claim; no directly recorded fuel-economy metric or sufficiently dense repeated use.", "verdict": "PARTIALLY SUPPORTED; EXPLORATORY ONLY"},
            {"id": 3, "question": "Show all ADAS disengagement events from yesterday.", "vehicle": "27 clip-level OpenLKA identities", "signals": ["adas.lateral_control_enabled","vehicle.speed"], "tables": ["canonical_measurement","overlay_event","event_window"], "coverage": "27 short clips; 25 have unix_time fields with repeated timestamps; registry spans 2023-11-21 to 2024-06-22. 55 real enable-state transitions (30 false→true, 25 true→false).", "provenance": "real state transitions; one synthetic ADAS reason example.", "limitations": "No data near 2026-11-05; state changes are not explicit OEM disengagement records and have no source reason codes; unix_time is repeated for many rows.", "verdict": "UNSUPPORTED FOR YESTERDAY; HISTORICAL STATE TRANSITIONS PARTIALLY AVAILABLE"},
            {"id": 4, "question": "What happened before the battery overheating warning?", "vehicle": "tum_bmw_i3:bmw_i3", "signals": ["battery.temperature","battery.temperature_max","thermal.coolant_temperature_inlet","thermal.coolant_temperature_heatercore","battery.soc","synthetic thermal.coolant_pump_duty","synthetic scenario.distractor_load"], "tables": ["canonical_measurement","overlay_event","overlay_sample","injection","injection_signal","event_window","derived_1hz"], "coverage": "70 measured trips, 10 Hz, 2019-06-25 to 2020-02-07; five seeded synthetic occurrences, four development and one held out; two untouched controls.", "provenance": "measured TUM backdrop; thermal overlays/warnings/DTC/freeze frames/QNX logs synthetic; evaluation labels in sidecar.", "limitations": "TUM has no pump-duty measurement and no real BATT_OVERTEMP event. Synthetic temporal precedence/recurrence is test evidence only, not causal evidence.", "verdict": "PARTIALLY SUPPORTED FOR SYNTHETIC PIPELINE TESTING ONLY"},
            {"id": 5, "question": "Compare energy consumption between city and highway driving.", "vehicle": "No source vehicle with verified city/highway labels", "signals": ["battery.current","battery.voltage","vehicle.speed","GPS on VED Leaf only"], "tables": ["canonical_measurement","vehicle_capability","trip_rollup"], "coverage": "VED Leaf has 293 trips and GPS; TUM has 70 trips but no GPS capability; comma segment is explicitly a highway segment but only one short RAV4 clip.", "provenance": "real measurements; no city/highway labels or route map-match outputs in this release.", "limitations": "Cannot make a measured city-versus-highway comparison without unsupported inferred classes; one comma highway segment is not a comparison.", "verdict": "UNSUPPORTED"},
        ]

        report = {
            "audit_timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "overall_verdict": "CONDITIONAL ACCEPT",
            "acceptance_scope": "internal engineering/development snapshot only; not cleared for external redistribution or claims that all five case-study questions are fully supported",
            "database": {"path": "data/processed/vehicle_gpt.sqlite", "bytes": DB.stat().st_size, "canonical_rows": validation["canonical_rows"], "vehicles": len(vehicle_rows), "trips": sum(x["trips"] for x in trip_counts), "layers": sorted(table_names)},
            "sources": {"raw_manifest_files": raw["file_count"], "raw_files_by_source": file_counts, "canonical_rows_by_source": source_counts, "trip_coverage_by_source": trip_counts},
            "vehicles": vehicle_rows,
            "quality": {"quality_flag_counts": quality, "out_of_range_details": invalid, "repeated_source_timestamps": duplicate_times, "duplicate_source_keys": duplicate_keys, "TUM_trip_signal_coverage": tum_signal_trip_coverage},
            "OpenLKA": {"timestamp_bounds": dict(open_timestamp), "real_state_transitions": open_transitions, "timestamp_anomalies": openlka_date_check},
            "overheating_scenario": {"thermal_injections": thermal, "untouched_controls": controls, "synthetic_event_counts": event_counts, "ground_truth_records": len(gt_injections), "ground_truth_signal_records": gt_signal_rows, "split_config": splits},
            "question_coverage": question_coverage,
            "environment": {"python": platform.python_version(), "pyyaml": yaml.__version__, "python_3_11_tested": False, "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None, "rlimit_as_bytes": resource.getrlimit(resource.RLIMIT_AS)[0], "rlimit_rss_bytes": resource.getrlimit(resource.RLIMIT_RSS)[0], "cgroup_memory_max_bytes": _memory_cap(), "arm_a55_measured": False},
            "licensing": [
                {"source": "VED", "local_evidence": "Apache-2.0 LICENSE present; repository README also states Apache-2.0", "status": "PASS WITH ATTRIBUTION", "reference": "https://github.com/gsoh/VED"},
                {"source": "TUM BMW i3", "local_evidence": "No license/terms file in supplied Measurement Data; IEEE DataPort DOI 10.21227/6JR9-5235", "status": "NOT VERIFIED; redistribution blocked pending terms review", "reference": "https://doi.org/10.21227/6JR9-5235"},
                {"source": "comma2k19", "local_evidence": "MIT LICENSE present in repository; dataset-specific record rights not explicit in inspected files", "status": "NOT VERIFIED FOR DATA REDISTRIBUTION", "reference": "https://github.com/commaai/comma2k19"},
                {"source": "OpenLKA", "local_evidence": "Current official terms require citation/attribution; no re-identification; raw video must not be redistributed. Applicability to supplied pre-release CSVs remains to be confirmed.", "status": "PASS WITH DATA-TERMS LIMITATION", "reference": "https://openlka.github.io/"},
            ],
            "checks": checks,
            "required_corrections": [
                "Use clip-relative OpenLKA Time for within-clip ordering or clearly flag unix_time-derived timestamps; do not claim timestamp-accurate 'yesterday' events.",
                "Confirm TUM and comma2k19 dataset reuse/redistribution terms before external distribution.",
                "Validate Python 3.11 compatibility in a Python 3.11 environment before claiming target-runtime support.",
                "Do not claim that range, fuel-efficiency trend, ADAS-yesterday, or city/highway questions are fully supported by the present data.",
            ],
        }
    finally:
        connection.close()
        gt.close()
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = audit()
    print(json.dumps({"overall_verdict": result["overall_verdict"], "canonical_rows": result["database"]["canonical_rows"], "vehicles": result["database"]["vehicles"], "trips": result["database"]["trips"], "output": "data/manifests/acceptance_report.json"}, sort_keys=True))
