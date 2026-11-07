# Dataset Overview

## Purpose

This is a local engineering dataset for timeline, signal-availability, and
synthetic-diagnostic workflow tests. Passive measurements establish temporal
association, not causation. It is not a fleet-representative benchmark and does
not support every Case Study question with measured evidence.

## Sources and actual counts

| Source | Vehicles | Trips/clips | Canonical rows | Replay/source time coverage |
|---|---:|---:|---:|---|
| VED | 2 selected | 298 | 2,743,526 | 2017-11-05–2018-11-05; day-number-derived wall time, timezone unknown |
| TUM BMW i3 | 1 | 70 | 15,473,705 | 2019-06-25–2020-02-07; trip seconds plus Overview local date, timezone unknown |
| OpenLKA | 27 clip identities | 27 | 32,398 | registry bounds 2023-11-21–2024-06-22; unix_time duplicates within many clips, two clips lack absolute bounds |
| comma2k19 | 1 RAV4 identity | 1 segment | 29,844 | device-boot seconds only; no wall-clock replay bound |
| **Total** | **31** | **396** | **18,279,473** | Source time bases remain distinct |

The raw manifest covers 1,014 files: VED 6, TUM measurements 72, TUM simulation
48, comma2k19 61, and OpenLKA 827. TUM simulation files are checksummed but not
loaded into canonical measurements. The TUM source maps 15 signals; four are
not present across every trip (heater LIN power, heater-core temperature,
coolant-inlet temperature each appear in 50 trips; speed appears in 69).

## Real, synthetic, and derived data

- Canonical layer: 18,279,473 source-derived `real` rows. No synthetic values
  are stored in this table.
- Real overlays: 55 observed OpenLKA lateral-control state transitions (30
  false→true, 25 true→false). These are state changes, not reason-coded OEM
  disengagement records.
- Synthetic overlays: 41 events and 30,320 samples. Five thermal scenarios
  (four development recurrences, one held-out target), one held-out ADAS example,
  two untouched BMW i3 control trips, and synthetic diagnostic events.
- Ground truth: six injection records in a separate evaluation-only SQLite
  file and a JSON audit log.
- Derived layer: 2,913,307 one-second rows, 19,396 rollups, 81,492 event-window
  rows, and 51,617 deviation flags. No interpolation is marked or performed.

VED timestamps are reconstructed from `DayNum` and elapsed milliseconds using
the VED reference date. TUM samples are placed on the Overview date while
retaining trip-relative seconds. OpenLKA's `unix_time` is repeated at many
sample rows; absolute timing needs caution. comma2k19 uses boot-time seconds.
The transformation and its limitations are detailed in
[the architecture](DATASET_ARCHITECTURE.md) and [the quality report](DATA_QUALITY_REPORT.md).

## Vehicles and capabilities

The selected VED Leaf (`ved:455`) has 293 trips across 191 active dates and
speed, GPS, battery voltage/current/SOC, heater, and A/C signals. The diesel
example (`ved:119`) has five trips and 1,822 samples across five active dates.
The BMW i3 has battery, HVAC and thermal signals at 10 Hz, with SoC missing in
2.8127% of its samples. The comma2k19 RAV4 segment has six signals and validated
steering/wheel-speed decoding. OpenLKA clips provide speed and lateral-control
state only in this selected mapping.

See [vehicle and trip catalogue](VEHICLE_AND_TRIP_CATALOGUE.md) and
[signal catalogue](SIGNAL_CATALOGUE.md). Signal availability is per vehicle;
an absent capability row means the selected data does not provide that signal.

## Acceptance status and limits

The independent audit verdict is **CONDITIONAL ACCEPT for internal engineering
use**. The dataset does not fully support all five Case Study questions:
range is only proxied, fuel-economy evidence is sparse, “yesterday” is outside
the OpenLKA time span, the overheating pattern is synthetic, and city/highway
labels are absent. Python 3.11 and ARM A55 behavior remain untested; some
dataset redistribution terms remain unverified. See
[acceptance audit](DATASET_ACCEPTANCE_AUDIT.md) and
[question coverage](QUESTION_COVERAGE.md).
