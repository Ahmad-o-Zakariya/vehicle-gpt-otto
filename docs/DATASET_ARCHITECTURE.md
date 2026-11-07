# Dataset Architecture

## Five layers

```mermaid
flowchart LR
  RAW["RAW files + SHA-256 manifest"] --> INGEST["Offline source loaders"]
  INGEST --> CAN["CANONICAL SQLite measurements<br/>real only"]
  CAN --> CAP["Capability + source coverage"]
  CAN --> OVL["OVERLAY events and samples<br/>synthetic records stay separate"]
  CAN --> DER["DERIVED one-second tier, rollups,<br/>event windows, deviation flags"]
  OVL --> DER
  OVL --> GT["GROUND TRUTH sidecar + JSON<br/>evaluation only"]
  CAN -. "source IDs and provenance" .-> DER
  OPS["Operational inspection/query code"] --> CAN
  OPS --> OVL
  OPS --> DER
  OPS -. "never opens" .-> GT
```

| Layer | Location | Contents |
|---|---|---|
| RAW | `DATASET/` and `data/manifests/raw_files.json` | Immutable supplied files, size and SHA-256 |
| CANONICAL | `data/processed/vehicle_gpt.sqlite` | Long-format source measurements; `provenance='real'` only |
| OVERLAY | Main DB `overlay_event`, `overlay_sample` | Real observed OpenLKA state changes and separately labelled synthetic events/samples |
| GROUND TRUTH | `data/processed/ground_truth/ground_truth.sqlite`, `injections.json` | Injection parameters, values, labels, and split; evaluation-only |
| DERIVED | Main DB `derived_1hz`, `trip_rollup`, `event_window`, `deviation_flag` | Deterministic, rebuildable outputs from canonical plus overlay |

## Operational and evaluation separation

The operational database has no `injection`, `injection_signal`, or
`split_manifest` tables. Synthetic overlay rows carry an injection ID and are
validated against the sidecar. `scripts/inspect_dataset.py` cannot show
evaluation labels unless `--evaluation-only` precedes the
`evaluation-injections` command. No operational source module imports the
ground-truth database.

## Main database relationships

```mermaid
erDiagram
  vehicle_registry ||--o{ trip_registry : owns
  trip_registry ||--o{ canonical_measurement : contains
  signal_catalog ||--o{ canonical_measurement : types
  trip_registry ||--o{ overlay_event : annotates
  overlay_event ||--o{ overlay_sample : carries
  signal_catalog ||--o{ overlay_sample : types
  trip_registry ||--o{ derived_1hz : aggregates
  signal_catalog ||--o{ derived_1hz : types
  overlay_event ||--o{ event_window : centers
  vehicle_registry ||--o{ vehicle_capability : describes
  trip_registry ||--o{ signal_coverage : describes
```

The exact columns, nullability, key order, and foreign keys are in the generated
[data dictionary](DATA_DICTIONARY.md). Signal units are normalized in
`signal_catalog`; source units and original lexical values are retained on each
canonical row.

## Capability and data flow

`vehicle_capability` describes only observed canonical signals for each vehicle.
`signal_coverage` describes availability and missingness per trip/signal.
Synthetic-only signals do not create measured capabilities. A signal request
without a capability row must be treated as insufficient evidence.

```mermaid
flowchart TD
  F[Source files] --> L[Streaming/read-only loaders]
  L --> M[Canonical measurements]
  M --> C[Capability + coverage]
  M --> S[Seeded overlay generator]
  S --> O[Overlay tables]
  S --> E[Separate evaluation labels]
  M --> D[Derived builder]
  O --> D
  D --> H[Stable derived-output hashes]
```

Replay rules, conversions, and no-interpolation policy are documented in
[derived method](derived_method.md) and [capability coverage](capability_coverage.md).
