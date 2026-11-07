# Deterministic Analysis Engines

`VehicleRepository` is read-only and rejects ground-truth paths. It provides
vehicle capability, canonical sample, overlay event, event window, and evidence
resolution queries. Four typed engines are registered:

- **Events:** event filtering by vehicle, interval and type. OpenLKA enable-state
  changes are not recast as OEM disengagement reasons.
- **Trends:** mean/median/min/max, absolute/relative change, hourly slope,
  sampling-gap irregularity and missing-row counts. It excludes missing/flagged
  points and never interpolates.
- **Comparisons:** trip-group means for a single signal and unit. The city/highway
  path fails closed because there are no verified labels or route classes.
- **Precursors:** event-centred stored ±60-second rows, with real/synthetic
  provenance preserved. Results state temporal association, never causation.

Each result includes engine/version, query ID, vehicle/trips, time range, method,
units, references, coverage, missing data, provenance, limitations and latency.
Coverage failures distinguish unavailable signals, missing history, missing
events, insufficient trips, and unsupported comparisons. Statistics use at most
100,000 database rows per request and return at most 2,000 plot points.
