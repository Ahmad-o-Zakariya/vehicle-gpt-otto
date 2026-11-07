# Canonical Schema and Signal Catalogue

## Storage decision

Use SQLite for the local single-file dataset: it is part of Python's standard library, supports indexed historical lookup and foreign keys, and keeps this phase dependency-light. The main database contains source telemetry, overlays, and derived data. Ground truth and its split manifest use a separate evaluation-only database/file and JSON log; query-facing code must not attach or open that file.

The DDL is in `src/vehicle_gpt/storage/schema.sql` and the isolated evaluation schema is in `src/vehicle_gpt/ground_truth/schema.sql`. The catalogue is `configs/signals.yaml`.
The catalogue contains 24 source-measured signals plus two explicitly synthetic
overlay signals (`thermal.coolant_pump_duty`, `scenario.distractor_load`).

## Timestamp fields

- `ts_source` stores the source timestamp text exactly as parsed (numeric lexical form or original timestamp string).
- `ts_source_seconds` stores numeric source time in seconds where the source has an elapsed numeric clock.
- `timestamp_basis` describes whether the timestamp is wall-clock, trip-relative, device-boot-relative, or another source basis.
- `ts_replay` stores a normalized searchable ISO timestamp only when its date/time basis is defensible; `ts_replay_ns` is its sortable integer representation where available.
- Source time and replay time are never conflated. Timezone remains unspecified when the source does not provide one.

## Provenance semantics

- `real`: unmodified measurement or event directly observed in source files. Canonical measurements must use this value.
- `synthetic`: generated overlay event/sample or synthetic-only record; it must carry an injection ID and evaluation record.
- `real+overlay`: a derived context/result that combines an unchanged real measurement with a separately stored overlay. It never authorizes overwriting the source measurement.

Quality flags are explicit strings/JSON lists; source NaN/blank, nonfinite values, duplicates, gaps, out-of-range values and interpolation are distinguishable. Missing values are not filled or clipped. Derived rows record aggregation method, sample count and whether interpolation occurred.

## Table map

| Layer / registry | Tables |
|---|---|
| Signal catalogue | `signal_catalog` |
| Vehicle/trip registry | `vehicle_registry`, `trip_registry` |
| Canonical measurements | `canonical_measurement` |
| Overlay | `overlay_event`, `overlay_sample` |
| Derived | `derived_1hz`, `trip_rollup`, `event_window`, `deviation_flag`, `signal_coverage`, `vehicle_capability` |
| Raw provenance | `dataset_manifest` |
| Evaluation-only sidecar | `injection`, `injection_signal`, `split_manifest` in the separate ground-truth schema |

The canonical layer preserves source record/field identity and source lexical values, with unique constraints preventing duplicate import of the same source row. A/EV and B/TUM vehicles remain distinct by vehicle identity. Signal availability and quality are queryable from `vehicle_capability` before an answer is attempted.

## Unit conversions

- km/h → m/s: `value / 3.6` (VED, TUM); comma2k19 speed is already documented as m/s.
- TUM A/C kW → W: `value * 1000`; VED A/C watts are read from `Air Conditioning Power[Watts]` because the parallel kW field is entirely NaN for selected Leafs.
- TUM heating CAN kW → W: `value * 1000`; heating LIN and VED heater watts remain unchanged and are kept as separate source mappings.
- Boolean `op_lat_enable` → numeric canonical boolean: true=1, false=0.
- Toyota DBC wheel speed km/h → m/s: `value / 3.6`; steering angle plus fraction and four wheel-speed signals match all paired processed samples in the selected segment.
- Battery voltage/current/SOC and GPS degrees are unchanged. Current sign conventions are preserved source by source.

Expected rates are source-specific. VED cadence is irregular and is measured from timestamps, not normalized to a claimed single rate. TUM measurements are 10 Hz. OpenLKA files use the 10 Hz sample routes in this local subset. Unknown rates remain null until measured. Plausibility ranges are validation flags only, not clipping rules or proof of source-valid operating limits.
