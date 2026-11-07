# Synthetic overlay and evaluation method

`configs/injections.yaml` fixes seed `20261106`, trip selection, event timing
range, and signal changes. `scripts/generate_overlays.py` uses a seeded PRNG to
select event offsets and is safe to rerun: it replaces only synthetic overlay
rows and regenerates the evaluation sidecar and JSON log. Canonical source rows
are never updated.

Five BMW i3 winter trips form a repeated synthetic thermal pattern. Four are
development injections; the January 5 target trip is held out. Each event
contains a synthetic pump-duty drop, a 20 °C ramp added to measured
`battery.temperature` in the overlay layer, a `BATT_OVERTEMP` warning, an
unrelated synthetic distractor change, and a
60-second-before/after coolant-inlet dropout. Pump duty is explicitly synthetic
because the TUM files contain no pump-duty channel. The held-out target and
every generated sample preserve the original measured value in the sidecar.
The series has four development recurrences and one held-out target. `TripA01`
and `TripB02` are untouched real-measurement controls. No event asserts causal
attribution.

The OpenLKA sample has observed controller enable-state transitions but no
reason codes. One held-out synthetic disengagement is added with reason code
`CAMERA_OCCLUSION_SYNTHETIC`; the reason is not presented as observed data.
Each thermal occurrence also receives synthetic warning, DTC, freeze-frame,
and QNX-style log events. The DTC label is explicitly non-OEM and synthetic.

All synthetic overlay events are linked by injection ID to
`data/processed/ground_truth/ground_truth.sqlite`. The sidecar stores split,
parameters, affected signal values, and expected label; the companion
`data/processed/ground_truth/injections.json` is the machine-readable audit log.
Neither ground-truth tables nor labels exist in the main query-facing database.
The split manifest reserves the target variant and ADAS-reason family for
held-out testing.

Regenerate with `scripts/run_limited.sh python3 scripts/generate_overlays.py`.
