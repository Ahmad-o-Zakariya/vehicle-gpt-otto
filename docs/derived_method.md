# Derived data method

`scripts/build_derived.py` deterministically rebuilds Layer 5 from canonical
measurements and synthetic overlay samples. At identical timestamps an overlay
replaces the canonical value only in the derived view; Layer 2 remains intact.
Other real samples in a bucket remain, so mixed buckets carry `real+overlay`
provenance. Synthetic-only buckets carry `synthetic` provenance.

`derived_1hz` groups source-derived samples into one-second coordinates and uses
their arithmetic mean rounded to eight decimal places. It records input row
count and a quality summary. There is no interpolation. Sources without a
replay wall-clock coordinate use their source-relative seconds as the searchable
coordinate; `trip_registry.timestamp_basis` identifies that coordinate.

`trip_rollup` contains per-signal mean/min/max, valid/missing bucket counts,
coverage, and span, plus a speed-integral distance estimate. The distance
estimate omits missing seconds and is not an OEM odometer measurement.
`event_window` contains available 1 Hz values within ±60 seconds of each event.
`deviation_flag` is a causal trailing check: after 10 prior valid samples, a
value is flagged when it differs from the prior 60-sample mean by more than
three standard deviations (with a 0.5 °C temperature floor or 0.1-unit floor
for other signals). A source gap over two seconds resets the baseline. This is
a screening flag, not a diagnostic threshold.

The derived rebuild test executes the same fixture twice and compares all
outputs. The full-data hash manifest is
`data/manifests/derived_output_hashes.json`; use
`scripts/run_limited.sh python3 scripts/build_derived.py --verify-reproducible`
to rebuild twice and compare stable row hashes.
