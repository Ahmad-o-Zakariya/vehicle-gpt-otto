# Dataset Acceptance Audit

## Decision

**CONDITIONAL ACCEPT** for internal development and pipeline evaluation only. This is not a v1.0.0 acceptance and does not authorize external redistribution.

The audit uses read-only inspection of the generated dataset and the recorded validator output. Full machine-readable evidence is in [`acceptance_report.json`](../data/manifests/acceptance_report.json).

## Acceptance checks

| Check | Result | Evidence |
|---|---|---|
| database_integrity_and_foreign_keys | PASS | SQLite integrity_check and foreign_key_check recorded in validation report. |
| raw_checksums_and_file_classification | PASS | {"classification": {"comma2k19": 61, "openlka": 827, "tum_bmw_i3": 72, "tum_simulation": 48, "ved": 6}, "files": 1014} |
| canonical_provenance_and_source_keys | PASS | {"canonical_real_rows": 18279473, "duplicate_source_keys": 0} |
| overlay_trace_and_ground_truth_isolation | PASS | {"ground_truth_signal_rows": 30320, "main_has_ground_truth_tables": false, "overlay_samples": 30320, "synthetic_events": 41} |
| timestamp_order_and_uniqueness | PASS WITH LIMITATIONS | {"OpenLKA_unix_time_repeated_groups": 98, "extra_rows_at_repeated_timestamps": 4876, "interpretation": "source rows remain unique, but OpenLKA unix_time is not unique at sample cadence; absolute event timing must be treated cautiously."} |
| quality_and_signal_coverage | PASS WITH LIMITATIONS | {"TUM_trip_signal_coverage": [{"missing": 0, "rows": 1094793, "signal": "battery.current", "trips": 70}, {"missing": 30793, "rows": 1094793, "signal": "battery.soc", "trips": 70}, {"missing": 0, "rows": 1094793, "signal": "battery.temperature", "trips": 70}, {"missing": 0, "rows": 1094793, "signal": "battery.temperature_max", "trips": 70}, {"missin |
| derived_reproducibility | PASS | {"derived_1hz": 2913307, "deviation_flag": 51617, "event_window": 81492, "trip_rollup": 19396} |
| python_3_11_compatibility_and_target_hardware | NOT VERIFIED | Local scripts/tests ran under Python 3.14; project declares Python >=3.11,<3.12. No ARM A55 device run. RLIMIT_AS is 2 GiB; RLIMIT_RSS is not enforced. |
| redistribution_rights | NOT VERIFIED | TUM reuse terms and comma2k19 dataset-specific rights are unclear; OpenLKA data has separate terms. Internal-only handling pending review. |

## Conditions before broader release

- Use clip-relative OpenLKA Time for within-clip ordering or clearly flag unix_time-derived timestamps; do not claim timestamp-accurate 'yesterday' events.
- Confirm TUM and comma2k19 dataset reuse/redistribution terms before external distribution.
- Validate Python 3.11 compatibility in a Python 3.11 environment before claiming target-runtime support.
- Do not claim that range, fuel-efficiency trend, ADAS-yesterday, or city/highway questions are fully supported by the present data.

## Scope and environment

- 18,279,473 canonical real measurements across 31 registry identities and 396 trips.
- Source checksums, SQLite integrity, foreign keys, provenance, and deterministic derived hashes passed in the recorded validation.
- Runtime observed: Python 3.14.4; target is Python 3.11. Target-runtime compatibility remains unverified.
- Question-specific limits are documented in [question coverage](QUESTION_COVERAGE.md); quality findings are in [data quality report](DATA_QUALITY_REPORT.md).
