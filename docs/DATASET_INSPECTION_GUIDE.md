# Dataset Inspection Guide

## CLI

Use `scripts/inspect_dataset.py --help` for commands. It opens SQLite with `mode=ro` and `PRAGMA query_only=ON`.

```sh
python3 scripts/inspect_dataset.py summary
python3 scripts/inspect_dataset.py vehicles
python3 scripts/inspect_dataset.py vehicle --vehicle ved:455
python3 scripts/inspect_dataset.py trips --vehicle tum_bmw_i3:bmw_i3 --limit 10
python3 scripts/inspect_dataset.py signals --vehicle tum_bmw_i3:bmw_i3
python3 scripts/inspect_dataset.py signal --signal battery.temperature
python3 scripts/inspect_dataset.py provenance --limit 10
python3 scripts/inspect_dataset.py quality
python3 scripts/inspect_dataset.py events --limit 20
python3 scripts/inspect_dataset.py schema
python3 scripts/inspect_dataset.py sample --vehicle tum_bmw_i3:bmw_i3 --signal battery.temperature --limit 20
python3 scripts/inspect_dataset.py export --help
```

`export` requires a vehicle, signal, and bounded output path. The CLI rejects signals unavailable for a vehicle instead of returning fabricated or empty evidence. For evaluation-only labels, place `--evaluation-only` before `evaluation-injections`; those labels are not query-facing data.

## SQLite GUI

Open `data/processed/vehicle_gpt.sqlite` in DB Browser for SQLite using its read-only/open-existing option. Keep “write changes” disabled. Use the Browse Data tab for tables and Execute SQL for targeted queries. Do not open `ground_truth.sqlite` during operational inspection; it contains evaluation-only labels.

Example targeted queries:

```sql
SELECT vehicle_id, source_dataset, make, model, model_year, powertrain
FROM vehicle_registry ORDER BY vehicle_id;

SELECT signal, unit, sample_count, missing_rate, expected_sampling_hz,
       observed_sampling_hz
FROM vehicle_capability
WHERE vehicle_id = 'tum_bmw_i3:bmw_i3'
ORDER BY signal;

SELECT trip_id, signal, COUNT(*) AS rows, MIN(ts_source_seconds),
       MAX(ts_source_seconds)
FROM canonical_measurement
WHERE vehicle_id = 'tum_bmw_i3:bmw_i3'
  AND signal = 'battery.temperature'
GROUP BY trip_id, signal ORDER BY trip_id;
```

See [data dictionary](DATA_DICTIONARY.md) for key fields and [signal catalogue](SIGNAL_CATALOGUE.md) for units and coverage.
