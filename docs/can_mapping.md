# comma2k19 CAN Mapping Verification

## Source and vehicle identification

The selected local segment is b0c9d2329ad1606b|2018-08-02--08-34-47/40. The comma2k19 README maps dongle ID b0c9d2329ad1606b to a Toyota RAV4. The exact model year is not present in the segment metadata. OpenDBC lists the Toyota RAV4 2017–18 platform with powertrain DBC toyota_new_mc_pt_generated; the pinned signal layouts used here are captured in configs/comma2k19_dbc.yaml and implemented in src/vehicle_gpt/ingest/comma2k19.py.

## Verified mapping

- CAN ID 0x025 (STEER_ANGLE_SENSOR): signed Motorola STEER_ANGLE at bit 3, length 12, factor 1.5 deg; plus signed STEER_FRACTION at bit 39, length 4, factor 0.1 deg.
- CAN ID 0x0AA (WHEEL_SPEEDS): unsigned Motorola wheel signals at bit starts 7 (FR), 23 (FL), 39 (RR), 55 (RL), each length 16, factor 0.01 and offset −67.67 km/h. Convert to canonical m/s with ((raw × 0.01) − 67.67) / 3.6.
- The sampled segment contains 135,468 raw frames: 4,974 frames at ID 0x025, 4,974 at ID 0x0AA, and 2,487 at ID 0x0B4. Only steering and wheel-speed mappings are claimed as verified by this check; the 0x0B4 speed message is not used by the adapter.

## Replay comparison

The decoder is compared at matching source timestamps against the supplied processed CAN arrays:

- Steering: all 4,974 samples compared; maximum absolute difference 0.0 degrees.
- Four wheel-speed channels: 4,974 time samples / 19,896 values compared; maximum absolute difference 3.552713678800501e-15 m/s (floating-point representation only).
- Tolerance: 1e-9 in canonical units.
- Automated report: data/manifests/comma_dbc_validation.json.
- Re-run: python3 scripts/verify_comma_dbc.py.

This validates the frame/signal mapping for this segment against the dataset's paired processed outputs. It does not establish an OEM model-year/trim identity, validate every Toyota RAV4, or provide an OEM-certified decoder.
