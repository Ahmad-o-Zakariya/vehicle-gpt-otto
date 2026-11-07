-- This schema belongs in a separate evaluation-only database/file.
-- Query-facing code must not attach or open this database.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS injection (
    injection_id TEXT PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    trip_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ts_replay_ns INTEGER NOT NULL,
    random_seed INTEGER NOT NULL,
    parameters_json TEXT NOT NULL,
    expected_label TEXT NOT NULL,
    split TEXT NOT NULL CHECK (split IN ('train_development', 'held_out_test')),
    overlay_event_ids_json TEXT NOT NULL,
    created_by_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS injection_signal (
    injection_id TEXT NOT NULL,
    signal TEXT NOT NULL,
    ts_replay_ns INTEGER NOT NULL,
    original_value REAL,
    injected_value REAL,
    unit TEXT NOT NULL,
    PRIMARY KEY (injection_id, signal, ts_replay_ns),
    FOREIGN KEY (injection_id) REFERENCES injection(injection_id)
);

CREATE TABLE IF NOT EXISTS split_manifest (
    injection_id TEXT PRIMARY KEY,
    split TEXT NOT NULL CHECK (split IN ('train_development', 'held_out_test')),
    pattern_family TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_sha256 TEXT NOT NULL,
    FOREIGN KEY (injection_id) REFERENCES injection(injection_id)
);
