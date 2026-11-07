PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS signal_catalog (
    signal TEXT PRIMARY KEY,
    canonical_unit TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type IN ('float', 'integer', 'boolean')),
    expected_sampling_hz REAL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicle_registry (
    vehicle_id TEXT PRIMARY KEY,
    source_vehicle_key TEXT NOT NULL,
    source_dataset TEXT NOT NULL,
    make TEXT,
    model TEXT,
    model_year INTEGER,
    powertrain TEXT,
    identity_evidence TEXT NOT NULL,
    UNIQUE (source_dataset, source_vehicle_key)
);

CREATE TABLE IF NOT EXISTS trip_registry (
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    source_trip_key TEXT NOT NULL,
    source_dataset TEXT NOT NULL,
    ts_source_start TEXT,
    ts_source_end TEXT,
    timestamp_basis TEXT NOT NULL,
    ts_replay_start TEXT,
    ts_replay_end TEXT,
    provenance TEXT NOT NULL CHECK (provenance IN ('real', 'real+overlay', 'synthetic')),
    PRIMARY KEY (vehicle_id, trip_id),
    FOREIGN KEY (vehicle_id) REFERENCES vehicle_registry(vehicle_id)
);

CREATE TABLE IF NOT EXISTS canonical_measurement (
    measurement_id INTEGER PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    ts_source TEXT NOT NULL,
    ts_source_seconds REAL,
    ts_replay TEXT,
    ts_replay_ns INTEGER,
    timestamp_basis TEXT NOT NULL,
    value REAL,
    quality_flag TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance = 'real'),
    source_dataset TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    source_field TEXT NOT NULL,
    source_unit TEXT NOT NULL,
    source_value TEXT,
    UNIQUE (source_dataset, source_file, source_row, source_field),
    FOREIGN KEY (vehicle_id, trip_id) REFERENCES trip_registry(vehicle_id, trip_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);
CREATE INDEX IF NOT EXISTS idx_measurement_vehicle_signal_time
    ON canonical_measurement(vehicle_id, signal, ts_replay_ns);
CREATE INDEX IF NOT EXISTS idx_measurement_trip_signal_source_time
    ON canonical_measurement(vehicle_id, trip_id, signal, ts_source_seconds);

CREATE TABLE IF NOT EXISTS overlay_event (
    event_id TEXT PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts_source TEXT,
    ts_replay TEXT,
    ts_replay_ns INTEGER,
    provenance TEXT NOT NULL CHECK (provenance IN ('real', 'synthetic')),
    injection_id TEXT,
    event_metadata_json TEXT NOT NULL,
    FOREIGN KEY (vehicle_id, trip_id) REFERENCES trip_registry(vehicle_id, trip_id),
    CHECK ((provenance = 'synthetic' AND injection_id IS NOT NULL) OR provenance = 'real')
);
CREATE INDEX IF NOT EXISTS idx_overlay_event_time
    ON overlay_event(vehicle_id, ts_replay_ns, event_type);
CREATE TABLE IF NOT EXISTS overlay_sample (
    overlay_sample_id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    ts_replay_ns INTEGER NOT NULL,
    value REAL,
    quality_flag TEXT NOT NULL,
    injection_id TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'synthetic' CHECK (provenance = 'synthetic'),
    FOREIGN KEY (event_id) REFERENCES overlay_event(event_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);
CREATE INDEX IF NOT EXISTS idx_overlay_sample_signal_time
    ON overlay_sample(signal, ts_replay_ns);

CREATE TABLE IF NOT EXISTS derived_1hz (
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    bucket_start_ns INTEGER NOT NULL,
    value REAL,
    sample_count INTEGER NOT NULL,
    aggregation_method TEXT NOT NULL,
    interpolated INTEGER NOT NULL DEFAULT 0 CHECK (interpolated IN (0, 1)),
    quality_flag TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('real', 'real+overlay', 'synthetic')),
    PRIMARY KEY (vehicle_id, trip_id, signal, bucket_start_ns),
    FOREIGN KEY (vehicle_id, trip_id) REFERENCES trip_registry(vehicle_id, trip_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);

CREATE TABLE IF NOT EXISTS trip_rollup (
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    coverage REAL,
    method TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, trip_id, metric),
    FOREIGN KEY (vehicle_id, trip_id) REFERENCES trip_registry(vehicle_id, trip_id)
);

CREATE TABLE IF NOT EXISTS event_window (
    event_id TEXT NOT NULL,
    offset_seconds INTEGER NOT NULL CHECK (offset_seconds BETWEEN -60 AND 60),
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    value REAL,
    quality_flag TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('real', 'real+overlay', 'synthetic')),
    source_measurement_id INTEGER,
    PRIMARY KEY (event_id, offset_seconds, signal),
    FOREIGN KEY (event_id) REFERENCES overlay_event(event_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal),
    FOREIGN KEY (source_measurement_id) REFERENCES canonical_measurement(measurement_id)
);

CREATE TABLE IF NOT EXISTS deviation_flag (
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    bucket_start_ns INTEGER NOT NULL,
    value REAL NOT NULL,
    baseline_mean REAL NOT NULL,
    baseline_stddev REAL NOT NULL,
    threshold REAL NOT NULL,
    rule_id TEXT NOT NULL,
    quality_flag TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance IN ('real', 'real+overlay', 'synthetic')),
    PRIMARY KEY (vehicle_id,trip_id,signal,bucket_start_ns,rule_id),
    FOREIGN KEY (vehicle_id,trip_id) REFERENCES trip_registry(vehicle_id,trip_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);

CREATE TABLE IF NOT EXISTS signal_coverage (
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    first_ts_replay_ns INTEGER,
    last_ts_replay_ns INTEGER,
    expected_interval_seconds REAL,
    observed_interval_median_seconds REAL,
    sample_count INTEGER NOT NULL,
    missing_count INTEGER NOT NULL,
    missing_rate REAL,
    coverage REAL,
    quality_summary_json TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, trip_id, signal),
    FOREIGN KEY (vehicle_id, trip_id) REFERENCES trip_registry(vehicle_id, trip_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);

CREATE TABLE IF NOT EXISTS vehicle_capability (
    vehicle_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_dataset TEXT NOT NULL,
    first_ts_replay_ns INTEGER,
    last_ts_replay_ns INTEGER,
    expected_sampling_hz REAL,
    observed_sampling_hz REAL,
    sample_count INTEGER NOT NULL,
    missing_rate REAL,
    coverage REAL,
    quality_summary_json TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (vehicle_id, signal),
    FOREIGN KEY (vehicle_id) REFERENCES vehicle_registry(vehicle_id),
    FOREIGN KEY (signal) REFERENCES signal_catalog(signal)
);

CREATE TABLE IF NOT EXISTS dataset_manifest (
    source_dataset TEXT NOT NULL,
    source_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    immutable INTEGER NOT NULL CHECK (immutable = 1),
    PRIMARY KEY (source_dataset, source_path)
);
