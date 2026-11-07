#!/usr/bin/env python3
"""Generate schema, signal, and vehicle catalogue snapshots from the active release."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/processed/vehicle_gpt.sqlite"


def _cell(text) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def generate_dictionary(connection):
    lines = [
        "# Dataset Dictionary", "",
        "This snapshot is generated from `PRAGMA table_info` and foreign-key metadata in the operational database.",
        "`PK` gives primary-key order; `NOT NULL` is the database constraint. Units for signal values are defined by `signal_catalog` and the `unit` column on each measurement/derived row.",
        "Synthetic evaluation labels are only in the separate ground-truth database described below.", "",
    ]
    tables = [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    for table in tables:
        columns = connection.execute(f"PRAGMA table_info('{table}')").fetchall()
        foreign_keys = connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
        lines += [f"## `{table}`", "", "| Column | SQLite type | Nullability | PK order | Default |", "|---|---|---|---:|---|"]
        for col in columns:
            lines.append(f"| `{col[1]}` | {_cell(col[2])} | {'NOT NULL' if col[3] else 'NULL allowed'} | {col[5] or '—'} | {_cell(col[4])} |")
        if foreign_keys:
            lines += ["", "Foreign keys:"]
            lines.extend(
                f"- `{fk[3]}` → `{fk[2]}.{fk[4]}`" for fk in foreign_keys
            )
        else:
            lines += ["", "Foreign keys: none."]
        lines.append("")
    lines += [
        "## Separate evaluation database", "",
        "`data/processed/ground_truth/ground_truth.sqlite` contains `injection`, `injection_signal`, and `split_manifest`. It is evaluation-only and must not be opened by operational query processing. The JSON audit log is `data/processed/ground_truth/injections.json`.", "",
        "## Provenance", "",
        "- Canonical measurements: `real` only.",
        "- Source-observed state-change events: `real` and trace to source file/row metadata.",
        "- Generated events/samples: `synthetic` and linked to an injection ID.",
        "- Derived buckets that combine unchanged real values and overlay values: `real+overlay`.", "",
    ]
    (ROOT / "docs/DATA_DICTIONARY.md").write_text("\n".join(lines), encoding="utf-8")


def generate_signals(connection):
    catalogue = yaml.safe_load((ROOT / "configs/signals.yaml").read_text(encoding="utf-8"))
    counts = {}
    for row in connection.execute(
        """SELECT signal,source_dataset,COUNT(DISTINCT vehicle_id),SUM(sample_count),
                  MIN(observed_sampling_hz),MAX(observed_sampling_hz)
           FROM vehicle_capability GROUP BY signal,source_dataset"""
    ):
        counts.setdefault(row[0], []).append(row[1:])
    lines = [
        "# Signal Catalogue", "",
        "Canonical units and source mappings come from `configs/signals.yaml`; availability and observed rates below come from the current `vehicle_capability` table. Expected rates are not measured rates.", "",
        "| Signal | Description | Unit | Source mapping and conversion | Expected rate | Valid range | Measured availability |", "|---|---|---|---|---|---|---|",
    ]
    for name, spec in catalogue["signals"].items():
        mappings = []
        for m in spec.get("source_mappings", []):
            rate = f"; {m['expected_sampling_hz']} Hz expected" if m.get("expected_sampling_hz") else ""
            state = f"; {m['status']}" if m.get("status") else ""
            mappings.append(f"{m['dataset']}: `{m['field']}` ({m['source_unit']} → {spec['unit']}; {m['conversion']}{rate}{state})")
        if not mappings:
            mappings = ["Synthetic overlay only; no raw-source mapping."]
        expected = spec.get("expected_sampling_hz")
        expected_text = f"{expected:g} Hz" if expected else "measured from timestamps"
        valid = spec.get("valid_range")
        valid_text = "unbounded / not specified" if valid is None else f"{valid[0]} to {valid[1]}"
        availability = []
        for ds, vehicle_count, rows, low, high in counts.get(name, []):
            rate = f"; observed {low:.3f}–{high:.3f} Hz" if low is not None else ""
            availability.append(f"{ds}: {vehicle_count} vehicle(s), {rows} rows{rate}")
        if not availability and spec.get("provenance_expectations") == ["synthetic"]:
            availability = ["No real measurement capability; present only in synthetic overlays."]
        elif not availability:
            availability = ["Not present on selected vehicles."]
        lines.append(
            f"| `{name}` | {_cell(spec['description'])} | {_cell(spec['unit'])} | {'<br>'.join(mappings)} | {_cell(expected_text)} | {_cell(valid_text)} | {'<br>'.join(availability)} |"
        )
    lines += ["", "Range checks are quality flags; values are preserved. A flagged value does not automatically imply a source error when sign conventions are unknown.", ""]
    (ROOT / "docs/SIGNAL_CATALOGUE.md").write_text("\n".join(lines), encoding="utf-8")


def generate_vehicles(connection):
    vehicles = connection.execute(
        """SELECT v.vehicle_id,v.source_dataset,v.source_vehicle_key,v.make,v.model,v.model_year,
                  v.powertrain,v.identity_evidence,COUNT(t.trip_id),MIN(t.ts_replay_start),
                  MAX(t.ts_replay_end)
           FROM vehicle_registry v LEFT JOIN trip_registry t USING(vehicle_id)
           GROUP BY v.vehicle_id ORDER BY v.source_dataset,v.vehicle_id"""
    ).fetchall()
    lines = [
        "# Vehicle and Trip Catalogue", "",
        "Vehicle IDs preserve source identities. OpenLKA IDs are clip-level references and are not merged to assert physical vehicle identity. Dates retain source timezone semantics; null replay bounds indicate relative/boot-time sources.", "",
        "| Vehicle ID | Source / source key | Make / model / year / powertrain | Trips | First replay time | Last replay time | Signals | Identity and coverage notes |", "|---|---|---|---:|---|---|---:|---|",
    ]
    for row in vehicles:
        vehicle, dataset, source_key, make, model, year, powertrain, evidence, trips, start, end = row
        signals = connection.execute("SELECT COUNT(*) FROM vehicle_capability WHERE vehicle_id=?", (vehicle,)).fetchone()[0]
        identity = evidence
        if dataset == "ved" and vehicle.endswith(":119"):
            identity += "; diesel identity from VED static registry; make/model unresolved; five trips only"
        if dataset == "comma2k19":
            identity += "; selected route is a highway segment; exact model year/trim unknown"
        if dataset == "tum_bmw_i3":
            identity += "; no GPS latitude capability; source model year not asserted"
        lines.append(
            f"| `{vehicle}` | {dataset} / `{source_key}` | {_cell(' / '.join(str(x) for x in (make,model,year,powertrain) if x is not None))} | {trips} | {_cell(start)} | {_cell(end)} | {signals} | {_cell(identity)} |"
        )
    lines += [
        "", "Signal-level availability is listed in [Signal Catalogue](SIGNAL_CATALOGUE.md); trip IDs and timestamp bases are available with `scripts/inspect_dataset.py trips --vehicle VEHICLE_ID`.", "",
    ]
    (ROOT / "docs/VEHICLE_AND_TRIP_CATALOGUE.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        generate_dictionary(connection)
        generate_signals(connection)
        generate_vehicles(connection)
    finally:
        connection.close()
    print("generated docs/DATA_DICTIONARY.md, docs/SIGNAL_CATALOGUE.md, docs/VEHICLE_AND_TRIP_CATALOGUE.md")


if __name__ == "__main__":
    main()
