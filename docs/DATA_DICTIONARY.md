# Dataset Dictionary

This snapshot is generated from `PRAGMA table_info` and foreign-key metadata in the operational database.
`PK` gives primary-key order; `NOT NULL` is the database constraint. Units for signal values are defined by `signal_catalog` and the `unit` column on each measurement/derived row.
Synthetic evaluation labels are only in the separate ground-truth database described below.

## `canonical_measurement`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `measurement_id` | INTEGER | NULL allowed | 1 | — |
| `vehicle_id` | TEXT | NOT NULL | — | — |
| `trip_id` | TEXT | NOT NULL | — | — |
| `signal` | TEXT | NOT NULL | — | — |
| `unit` | TEXT | NOT NULL | — | — |
| `ts_source` | TEXT | NOT NULL | — | — |
| `ts_source_seconds` | REAL | NULL allowed | — | — |
| `ts_replay` | TEXT | NULL allowed | — | — |
| `ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `timestamp_basis` | TEXT | NOT NULL | — | — |
| `value` | REAL | NULL allowed | — | — |
| `quality_flag` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |
| `source_dataset` | TEXT | NOT NULL | — | — |
| `source_file` | TEXT | NOT NULL | — | — |
| `source_row` | INTEGER | NOT NULL | — | — |
| `source_field` | TEXT | NOT NULL | — | — |
| `source_unit` | TEXT | NOT NULL | — | — |
| `source_value` | TEXT | NULL allowed | — | — |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `dataset_manifest`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `source_dataset` | TEXT | NOT NULL | 1 | — |
| `source_path` | TEXT | NOT NULL | 2 | — |
| `size_bytes` | INTEGER | NOT NULL | — | — |
| `sha256` | TEXT | NOT NULL | — | — |
| `immutable` | INTEGER | NOT NULL | — | — |

Foreign keys: none.

## `derived_1hz`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `trip_id` | TEXT | NOT NULL | 2 | — |
| `signal` | TEXT | NOT NULL | 3 | — |
| `unit` | TEXT | NOT NULL | — | — |
| `bucket_start_ns` | INTEGER | NOT NULL | 4 | — |
| `value` | REAL | NULL allowed | — | — |
| `sample_count` | INTEGER | NOT NULL | — | — |
| `aggregation_method` | TEXT | NOT NULL | — | — |
| `interpolated` | INTEGER | NOT NULL | — | 0 |
| `quality_flag` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `deviation_flag`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `trip_id` | TEXT | NOT NULL | 2 | — |
| `signal` | TEXT | NOT NULL | 3 | — |
| `bucket_start_ns` | INTEGER | NOT NULL | 4 | — |
| `value` | REAL | NOT NULL | — | — |
| `baseline_mean` | REAL | NOT NULL | — | — |
| `baseline_stddev` | REAL | NOT NULL | — | — |
| `threshold` | REAL | NOT NULL | — | — |
| `rule_id` | TEXT | NOT NULL | 5 | — |
| `quality_flag` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `event_window`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `event_id` | TEXT | NOT NULL | 1 | — |
| `offset_seconds` | INTEGER | NOT NULL | 2 | — |
| `signal` | TEXT | NOT NULL | 3 | — |
| `unit` | TEXT | NOT NULL | — | — |
| `value` | REAL | NULL allowed | — | — |
| `quality_flag` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |
| `source_measurement_id` | INTEGER | NULL allowed | — | — |

Foreign keys:
- `source_measurement_id` → `canonical_measurement.measurement_id`
- `signal` → `signal_catalog.signal`
- `event_id` → `overlay_event.event_id`

## `overlay_event`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `event_id` | TEXT | NULL allowed | 1 | — |
| `vehicle_id` | TEXT | NOT NULL | — | — |
| `trip_id` | TEXT | NOT NULL | — | — |
| `event_type` | TEXT | NOT NULL | — | — |
| `ts_source` | TEXT | NULL allowed | — | — |
| `ts_replay` | TEXT | NULL allowed | — | — |
| `ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `provenance` | TEXT | NOT NULL | — | — |
| `injection_id` | TEXT | NULL allowed | — | — |
| `event_metadata_json` | TEXT | NOT NULL | — | — |

Foreign keys:
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `overlay_sample`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `overlay_sample_id` | INTEGER | NULL allowed | 1 | — |
| `event_id` | TEXT | NOT NULL | — | — |
| `signal` | TEXT | NOT NULL | — | — |
| `unit` | TEXT | NOT NULL | — | — |
| `ts_replay_ns` | INTEGER | NOT NULL | — | — |
| `value` | REAL | NULL allowed | — | — |
| `quality_flag` | TEXT | NOT NULL | — | — |
| `injection_id` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | 'synthetic' |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `event_id` → `overlay_event.event_id`

## `signal_catalog`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `signal` | TEXT | NULL allowed | 1 | — |
| `canonical_unit` | TEXT | NOT NULL | — | — |
| `data_type` | TEXT | NOT NULL | — | — |
| `expected_sampling_hz` | REAL | NULL allowed | — | — |
| `description` | TEXT | NOT NULL | — | — |

Foreign keys: none.

## `signal_coverage`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `trip_id` | TEXT | NOT NULL | 2 | — |
| `signal` | TEXT | NOT NULL | 3 | — |
| `unit` | TEXT | NOT NULL | — | — |
| `first_ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `last_ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `expected_interval_seconds` | REAL | NULL allowed | — | — |
| `observed_interval_median_seconds` | REAL | NULL allowed | — | — |
| `sample_count` | INTEGER | NOT NULL | — | — |
| `missing_count` | INTEGER | NOT NULL | — | — |
| `missing_rate` | REAL | NULL allowed | — | — |
| `coverage` | REAL | NULL allowed | — | — |
| `quality_summary_json` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `trip_registry`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `trip_id` | TEXT | NOT NULL | 2 | — |
| `source_trip_key` | TEXT | NOT NULL | — | — |
| `source_dataset` | TEXT | NOT NULL | — | — |
| `ts_source_start` | TEXT | NULL allowed | — | — |
| `ts_source_end` | TEXT | NULL allowed | — | — |
| `timestamp_basis` | TEXT | NOT NULL | — | — |
| `ts_replay_start` | TEXT | NULL allowed | — | — |
| `ts_replay_end` | TEXT | NULL allowed | — | — |
| `provenance` | TEXT | NOT NULL | — | — |

Foreign keys:
- `vehicle_id` → `vehicle_registry.vehicle_id`

## `trip_rollup`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `trip_id` | TEXT | NOT NULL | 2 | — |
| `metric` | TEXT | NOT NULL | 3 | — |
| `value` | REAL | NULL allowed | — | — |
| `unit` | TEXT | NOT NULL | — | — |
| `coverage` | REAL | NULL allowed | — | — |
| `method` | TEXT | NOT NULL | — | — |

Foreign keys:
- `vehicle_id` → `trip_registry.vehicle_id`
- `trip_id` → `trip_registry.trip_id`

## `vehicle_capability`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NOT NULL | 1 | — |
| `signal` | TEXT | NOT NULL | 2 | — |
| `unit` | TEXT | NOT NULL | — | — |
| `source_dataset` | TEXT | NOT NULL | — | — |
| `first_ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `last_ts_replay_ns` | INTEGER | NULL allowed | — | — |
| `expected_sampling_hz` | REAL | NULL allowed | — | — |
| `observed_sampling_hz` | REAL | NULL allowed | — | — |
| `sample_count` | INTEGER | NOT NULL | — | — |
| `missing_rate` | REAL | NULL allowed | — | — |
| `coverage` | REAL | NULL allowed | — | — |
| `quality_summary_json` | TEXT | NOT NULL | — | — |
| `provenance` | TEXT | NOT NULL | — | — |

Foreign keys:
- `signal` → `signal_catalog.signal`
- `vehicle_id` → `vehicle_registry.vehicle_id`

## `vehicle_registry`

| Column | SQLite type | Nullability | PK order | Default |
|---|---|---|---:|---|
| `vehicle_id` | TEXT | NULL allowed | 1 | — |
| `source_vehicle_key` | TEXT | NOT NULL | — | — |
| `source_dataset` | TEXT | NOT NULL | — | — |
| `make` | TEXT | NULL allowed | — | — |
| `model` | TEXT | NULL allowed | — | — |
| `model_year` | INTEGER | NULL allowed | — | — |
| `powertrain` | TEXT | NULL allowed | — | — |
| `identity_evidence` | TEXT | NOT NULL | — | — |

Foreign keys: none.

## Separate evaluation database

`data/processed/ground_truth/ground_truth.sqlite` contains `injection`, `injection_signal`, and `split_manifest`. It is evaluation-only and must not be opened by operational query processing. The JSON audit log is `data/processed/ground_truth/injections.json`.

## Provenance

- Canonical measurements: `real` only.
- Source-observed state-change events: `real` and trace to source file/row metadata.
- Generated events/samples: `synthetic` and linked to an injection ID.
- Derived buckets that combine unchanged real values and overlay values: `real+overlay`.
