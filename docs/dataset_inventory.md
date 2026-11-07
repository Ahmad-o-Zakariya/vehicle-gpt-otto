# Dataset Inventory — Phase 0

**Status:** source inventory complete; implementation and deeper format validation continue in subsequent phases.

## Findings and selection

| Role | Selection | Evidence | Limits |
|---|---|---|---|
| EV range/energy | VED Nissan Leaf, `VehId=455` | 293 trips, 303,824 records, 191 active days, `DayNum` 4.6983–369.7344, about 49.51 aggregate trip-hours; complete speed, GPS, heater watts, A/C watts, battery current, voltage and SOC fields in inspected rows | Fuel/MAF/RPM fields are absent for EVs. A/C kW field is all NaN; use its paired watts field. No source city/highway labels were identified. |
| VED candidate comparison | Leaf `VehId=10`: 201 trips/144 active days; Leaf `VehId=541`: 10 trips/6 active days | Same static registry identifies all three as EVs | `455` has the broadest trip count and active-day coverage. |
| ICE fuel signal | VED ICE `VehId=119` (`8-DSL 6.7L T/C`) | 5 trips, 1,822 records, 5 active days, measured fuel rate and speed are nonmissing in all inspected rows | Sparse history. Other high-coverage vehicles were missing actual fuel-rate values; MAF is not converted to fuel without an explicit engine/fuel model. Suitable for a limited measured-fuel example, not a robust seasonal trend. |
| Thermal/heating | TUM BMW i3, measurement trips A01–A32 and B01–B38 | 70 real-driving measurement files, 1,094,793 rows, timestamps at 0.1 s intervals, battery temperature, current, voltage, SOC, heating and A/C columns | Battery overtemperature is not represented. Pump-duty is absent; coolant volume flow appears in group B only (4.518% missing within B). The specified pump-duty / overheating scenario must be synthetic and isolated in overlay. |
| Real CAN replay | comma2k19 route `b0c9d2329ad1606b|2018-08-02--08-34-47`, segment `40` | Raw CAN arrays plus processed CAN speed, wheel-speed and steering-angle time/value arrays; upstream README identifies dongle `b0c9d2329ad1606b` as a RAV4 | Model year is not stated. Toyota RAV4 DBC frame/signal mapping is validated against the segment’s paired processed outputs; the exact year/trim remains unknown. |
| ADAS evidence | OpenLKA failure-sample CSVs | 27 CSVs, 14,999 rows; `op_lat_enable` has 30 false→true and 25 true→false transitions; 25/27 inspected files have Unix timestamps | This is an observed enable-state transition in sample data, not an OEM disengagement label. No reason-code/disengagement-reason columns were found. Use synthetic reason codes for explicit synthetic events; retain observed state transitions with their true semantics. |

### Vehicle time and rate notes

- VED `DayNum` is relative to 2017-11-01 00:00, per the included README. Dynamic timestamps are milliseconds within a trip. VED intervals are irregular: 100 ms is the most frequent observed step in selected vehicles, with substantial longer gaps (for example 200–1000 ms). Do not assign one fixed expected rate; record actual per-signal cadence and gaps.
- VED data represents roughly one year. Its source timestamps should be retained; the VED vehicle histories are not re-timed for the current plan.
- TUM timestamps are elapsed seconds per trip and reset to 0.0. The trip overview provides wall-clock starts from 2019-06-25 through 2020-02-07. Preserve both semantics; do not infer event wall time from relative time alone.
- TUM measurements are 10 Hz. Group A has 32 trips/467,701 rows; group B 38 trips/627,092 rows. No nonpositive timestamp steps or malformed-width records were observed. Relevant overall missingness: SoC 2.813%; coolant volume flow 2.588% overall (field is absent in A; 4.518% missing in B); battery temperature/current/voltage, speed, heating CAN/LIN, and A/C fields had no blanks/NaN in the inspected files.
- OpenLKA sample CSVs appear at approximately 10 Hz in the inspected routes (600 samples over about 60 seconds), matching the project's published description of 10 Hz partial routes. Two files lack `unix_time`; use their clip-local `Time` only and do not fabricate wall-clock alignment.
- comma2k19 upstream describes the example as a one-minute segment, with boot-time timestamps and separate value arrays. The selected raw CAN steering and four wheel-speed mappings have been replay-decoded and checked against every paired processed sample.

## Source files and formats

- VED: `DATASET/VED-master/Data/VED_DynamicData_Part1.7z` (82,773,769 bytes) and `VED_DynamicData_Part2.7z` (93,662,910 bytes). They contain 54 weekly CSVs total, 3,203,555,729 extracted bytes and 22,436,808 parseable rows across 32,552 (vehicle, trip) pairs. No malformed rows were encountered. Static registries are `VED_Static_Data_PHEV&EV.xlsx` and `VED_Static_Data_ICE&HEV.xlsx`.
- TUM measurements: 70 `TripA*.csv`/`TripB*.csv` plus `Overview.xlsx`; semicolon-separated, Windows-1252 encoded, 28 columns for A and 48 for B (including a blank trailing header in A). Units are largely in source header labels. Source trip starts and route/weather metadata are in `Overview.xlsx`.
- TUM simulation: 24 CSV plus 24 MAT files. CSVs have a descriptive category row and a second row of named signals and units; scenarios are separate from real measurements and must never be pooled as measured trips.
- comma2k19: one minute route segment with `raw_log.bz2`, `video.hevc`, global pose arrays, raw CAN arrays and processed CAN/GNSS/IMU arrays. Raw CAN arrays are under `processed_log/CAN/raw_can/{t,address,data,src}`. Processed CAN includes radar, speed, steering angle and wheel speed.
- OpenLKA: 27 CSVs (68–69 columns), JSON scene annotations and images in the local failure sample. Sample CSVs include `Time`, `unix_time`, `op_lat_enable`, lane model / visibility fields, steering and vehicle-state fields. Scene annotations describe visual conditions; they do not supply disengagement reason codes in the inspected sample.

## Data-quality measurements

- VED dynamic archives: 54 files, 22,436,808 parsed rows, 32,552 unique vehicle/trip pairs, no parser failures. Literal `NaN` values are present and must be counted as missing during ingestion. Selected EV #455 had 0% missing among GPS, speed, heater watts, A/C watts, HV current/SOC/voltage; MAF, engine RPM and fuel rate were 100% absent as expected for an EV. Selected ICE #119 had measured fuel rate and speed in all 1,822 rows, but has only five trips.
- TUM: file widths are consistent within each group. A has an unused blank trailing header column (14,244 blank cells); B has the missing values summarized above. The main battery temperature signal is present across all 1,094,793 rows. A coolant-pump-duty signal is not present in either measurement schema.
- OpenLKA: observed `op_lat_enable` transitions can be timestamped when `unix_time` exists; the reason for a transition is not recoverable from the inspected columns.
- comma2k19: raw CAN arrays and preprocessed channels are present. Exact decoder agreement, frame-level signal verification, raw frame counts, and duplicate/timestamp integrity will be tested by the CAN adapter work.

## DBC investigation

The comma2k19 repository states its first two dataset chunks are RAV4 data and maps dongle ID `b0c9d2329ad1606b` to the RAV4. OpenDBC lists a Toyota RAV4 2017–18 platform using `toyota_new_mc_pt_generated`; that DBC exposes `STEER_ANGLE_SENSOR.STEER_ANGLE` (with `STEER_FRACTION`) and `WHEEL_SPEEDS.WHEEL_SPEED_FL/FR` mappings. The selected segment's model year is not explicit in the supplied metadata. Raw steering and four wheel-speed mappings are verified against every paired processed sample (see [CAN mapping verification](can_mapping.md)); model year and trim remain unverified.

## Licensing and attribution

- VED includes an Apache License 2.0 file and README attribution to Oh, LeBlanc and Peng, 2020.
- comma2k19 includes a MIT LICENSE and citation details. No separate dataset-specific license statement was found in the local sample; verify appropriate data attribution before redistribution.
- The TUM local folders contain no license/terms file. The dataset is indexed as IEEE DataPort DOI `10.21227/6JR9-5235`, but the applicable reuse terms were not verified from a source license attached to these files.
- OpenLKA's current project page separates code/DBC MIT licensing from data terms: cite the paper and attribute OpenLKA; do not redistribute raw video. The inspected local checkout has no root `LICENSE` file, so data reuse is governed by the source terms rather than assuming the repo's README badge licenses every data artifact.
- Case Study PDF and TRACE deck are team reference materials, not data sources for canonical measurements.

## Evidence links

- [VED repository README](../DATASET/VED-master/README.md)
- [TUM IEEE DataPort record](https://doi.org/10.21227/6JR9-5235)
- [comma2k19 dataset README](https://github.com/commaai/comma2k19) — identifies the example segment structure and RAV4 dongle ID.
- [OpenDBC Toyota platform mapping](https://www.opendbc.com/cars/toyota-rav4-2017-18)
- [OpenLKA project data terms and sample rates](https://openlka.github.io/)

## Unverified items and decisions

- No local TUM license/terms file; confirm applicable reuse conditions before redistribution.
- The VED ICE fuel-rate-capable candidate is sparse (five trips). Keep query coverage honest and decline multiweek trend claims if evidence is inadequate.
- No direct TUM coolant pump duty or real battery-overtemperature warning exists in source measurements. Use only explicitly synthetic overlay events and ground truth for the proposed scenario.
- OpenLKA provides observed enable-state transitions, but not transition reasons in these local samples. Any reason code in a demo must be labeled synthetic.
- comma2k19 model year/trim identity remains unverified; validated mappings are limited to the selected segment and signals described in the CAN verification note.
- No source city/highway labels were identified for the chosen Leaf; any later comparison must state its classification method and avoid presenting inferred road type as source ground truth.
