# VehicleGPT Dataset Data Card

## Dataset summary

This offline, multi-source dataset supports engineering tests for vehicle
history lookup, signal availability, temporal evidence, and diagnostic-event
handling. It combines four supplied data sources while preserving vehicle,
trip, timestamp, unit, quality, source-row, and provenance fields. It is not a
fleet dataset and does not establish diagnostic causality.

## Sources and selected data

| Source | Selected content | Canonical rows | Time and identity limits |
|---|---|---:|---|
| VED | Nissan Leaf EV `VehId=455` and a limited measured diesel example `VehId=119` | 2,743,526 | `DayNum` is anchored at 2017-11-01 and combined with trip elapsed milliseconds. Timezone is unspecified. Vehicle 119 has sparse fuel-rate history. |
| TUM BMW i3 | 70 measured trips (32 A, 38 B), battery, thermal, HVAC, and vehicle channels | 15,473,705 | Overview dates run June 2019–February 2020. Trip-relative seconds are combined with Overview local wall time; timezone is unspecified. |
| OpenLKA | 27 local failure-sample clips | 32,398 | 25 clips have Unix timestamps; two remain clip-relative. 55 observed enable-state changes have no explicit reason code. Clip IDs are not merged into asserted physical vehicle identities. |
| comma2k19 | One RAV4 segment with processed speed and decoded raw steering/wheel speed | 29,844 | Boot-relative time only; route maps to a Toyota RAV4, but model year/trim are unknown. DBC checks are segment-specific. |

The canonical source layer totals 18,279,473 rows. The raw file manifest records
1,014 source files and SHA-256 checksums. TUM simulation data and commaCarSegments
are excluded from measured vehicle observations.

## Real, replayed, and synthetic records

Canonical measurements are source-derived and have `real` provenance. VED
timestamps are reconstructed from its documented elapsed-day origin; TUM
timestamps combine measured elapsed seconds with the supplied Overview date.
These transformations preserve sample intervals and trip ordering. No trip is
duplicated or synthetically placed on a real date. OpenLKA Unix times are kept
where supplied; clip-relative times remain relative. comma2k19 boot seconds are
not presented as wall-clock dates.

The main SQLite database stores 55 real OpenLKA controller-state transitions
as real overlay events. Phase 5 adds 41 explicitly synthetic events and 30,320
synthetic samples: five BMW i3 thermal patterns (four development recurrences
and one held-out target), one held-out synthetic ADAS disengagement, warnings,
DTCs, freeze frames, and QNX-style logs. Two BMW i3 trips are untouched
measurement controls. Pump duty is not present in TUM source files and exists
only as a synthetic overlay. The injected ADAS reason code is synthetic; the
local OpenLKA data has no reason field. `BATT_OVERTEMP` and the DTC are test
labels, not observed OEM diagnostics.

Original battery-temperature and coolant-inlet measurements remain unchanged
in canonical storage. Synthetic values, dropouts, and distractors live in the
overlay layer. Evaluation labels and original/injected values are stored only
in `data/processed/ground_truth/ground_truth.sqlite` and
`data/processed/ground_truth/injections.json`. Query-facing processing must not
open those files. Four injection IDs are development-only; the thermal target
and ADAS-reason family are held out.

## Processing and validation

Source mappings, units, missing-value rules, and known limits are documented
in [dataset inventory](dataset_inventory.md) and
[canonical schema](canonical_schema.md). Coverage uses source timestamps and
does not interpolate. Layer 5 uses one-second bucket means, trip rollups,
±60-second event windows, and causal trailing deviation flags. Full policies
are in [capability coverage](capability_coverage.md), [overlay method](overlay_method.md),
and [derived method](derived_method.md).
The final build contains 3,711 trip/signal coverage records, 89 vehicle/signal
capabilities, 2,913,307 normalized 1 Hz rows, 19,396 rollups, 81,492 event
windows, and 51,617 deviation flags. The full-data rebuild hashes are identical
across repeated generation; final checksum, integrity, and provenance results
are in `data/manifests/validation_report.json`.

The raw directory is immutable. Regenerate all processed outputs offline with
`scripts/build_pipeline.sh`; run `scripts/validate_dataset.py` afterward. The
pipeline runs with a two-CPU affinity and a 2 GiB virtual-address-space limit.
That limit is not a resident-memory cap. The current host provides Python
3.14.4, while the project target is Python 3.11; Python 3.11 validation remains
pending.

## Limitations and prohibited interpretations

- TUM has no coolant pump-duty measurement; synthetic pump overlays cannot
  support a claim that pump failure caused a temperature change.
- TUM's coolant-inlet dropout and distractor are deliberate synthetic tests.
- VED diesel fuel-rate evidence is too sparse for robust longitudinal trends;
  EV fuel/MAF/RPM channels are structurally absent.
- TUM BMW i3 has no GPS latitude capability in the selected measurement set.
- OpenLKA state transitions are controller observations, not explicit OEM
  disengagement reasons.
- comma2k19 DBC validation covers one segment and does not verify model year,
  trim, or other routes.
- Dataset coverage does not measure target-device latency, memory use,
  diagnostic accuracy, or performance at the case study's aspirational hardware
  limits.
- Do not present synthetic injections as real failures, use temporal order as
  causal proof, infer unavailable signals, or claim fleet-wide representativeness.

## Licensing and attribution

VED's local source archive includes Apache-2.0 terms. The comma2k19 repository
is MIT-licensed, but separate data terms were not independently verified. The
TUM source is cited by DOI `10.21227/6JR9-5235`; local redistribution terms were
not independently verified. OpenLKA's project page separates MIT code/DBC
licensing from its data terms; cite the OpenLKA paper and do not redistribute
raw video. Dataset terms are not fully verified for TUM and comma2k19. This snapshot is
conditional and for internal development only; confirm dataset-specific reuse
terms before any external redistribution. Acceptance conditions and question
coverage are recorded in [the acceptance audit](DATASET_ACCEPTANCE_AUDIT.md)
and [question matrix](QUESTION_COVERAGE.md). See [inventory citations and
license notes](dataset_inventory.md).

## Current release status

The audited snapshot is **CONDITIONAL ACCEPT for internal development only**. It is not a v1.0.0 release or a claim that all case-study questions are answerable. See [quality findings](DATA_QUALITY_REPORT.md) and [reproducibility instructions](REPRODUCIBILITY_GUIDE.md).
