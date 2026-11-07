# Capability and coverage outputs

`vehicle_capability` is rebuilt from canonical measurements by
`scripts/build_capabilities.py`. The script orders rows by vehicle, trip,
signal, and source seconds, then streams them without loading the table into
memory. It emits one row per observed trip/signal in `signal_coverage` and one
per vehicle/signal in `vehicle_capability`.

`sample_count` includes rows whose value is missing. `missing_count` counts
NULL values, and `quality_summary_json` retains every quality-flag count.
Observed interval medians include source-time gaps and repeated timestamps.
Observed vehicle cadence uses the positive source-time deltas. Expected cadence
comes from the signal catalogue's dataset mapping. Coverage is
`nonmissing samples / (observed duration * expected Hz + 1)`, capped at 1;
coverage is NULL when no expected rate is known. No value is interpolated.
First/last timestamps are source-derived replay coordinates where the source
provides one; device-boot and clip-relative sources retain NULL replay bounds.

Current result: 3,711 trip/signal rows and 89 vehicle/signal rows. All 89
capability records have real provenance; count/rate range checks found no
invalid entries. TUM BMW i3 battery channels with expected 10 Hz cadence report
approximately 10 Hz observed cadence. Battery SoC missing rate is 2.8127%.
The TUM BMW i3 has no `vehicle.latitude` capability row, so that request is
unsupported for this vehicle. Its 70 measured trips span June 2019 to February
2020. VED dates are reconstructed from `DayNum` using the dataset's documented
2017-11-01 origin; the source timezone remains unspecified.

Rebuild with `scripts/run_limited.sh python3 scripts/build_capabilities.py`.
