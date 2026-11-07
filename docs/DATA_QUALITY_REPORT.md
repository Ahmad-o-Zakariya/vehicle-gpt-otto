# Data Quality Report

## Summary

| Metric | Result |
|---|---:|
| Canonical source rows | 18,279,473 |
| Raw files with checksums | 1,014 |
| Duplicate canonical source keys | 0 |
| Repeated source timestamp groups | 98 (OpenLKA) |
| Extra rows sharing repeated timestamps | 4,876 |
| Interpolated rows | 0 |

## Missing values and range flags

Missing values remain missing; the pipeline does not fill them. Out-of-range values are retained and flagged, not clipped. Range checks indicate plausibility concerns, not definitive proof of physical invalidity.

| Source | Signal | Rows | Observed range |
|---|---|---:|---:|
| openlka | `vehicle.speed` | 181 | -0.06549303978681564 to -1.401298464324817e-45 |
| tum_bmw_i3 | `hvac.ac_power` | 1,461 | -170.0 to -10.0 |

TUM BMW i3 has 30,793 blank SoC values among 1,094,793 candidate rows (2.8127%). HVAC AC power has 1,461 negative values (-170 to -10 W); OpenLKA speed has 181 small negative values (-0.06549 to approximately 0 m/s). These values are retained with quality flags.

## OpenLKA timestamp caveat

The audit found 98 groups with repeated `unix_time` and 4,876 additional rows sharing timestamps. The CSV clip-relative `Time` advances within these groups. Use clip-relative time for within-clip order; avoid sample-cadence or “yesterday” claims based on the repeated Unix field. The 27 clip identities do not establish 27 distinct physical vehicles.

## Coverage caveats

- TUM has 70 measured trips; inlet/heater-core temperature and heater LIN power appear in 50 trips, while speed appears in 69.
- TUM has no GPS latitude capability in this selected measurement set.
- comma2k19 raw steering and wheel-speed validation covers one RAV4 segment.
- Synthetic samples/events are labeled synthetic. Evaluation ground truth remains in a sidecar.
