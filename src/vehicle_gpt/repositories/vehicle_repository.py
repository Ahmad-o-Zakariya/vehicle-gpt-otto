from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote


class VehicleRepository:
    """A query-only repository; ground-truth paths are deliberately rejected."""

    def __init__(self, database: Path):
        self.database = database.resolve()
        if "ground_truth" in self.database.parts:
            raise ValueError("operational repository cannot open ground truth")
        if not self.database.is_file():
            raise FileNotFoundError(self.database)

    def connect(self) -> sqlite3.Connection:
        uri = f"file:{quote(str(self.database), safe='/')}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA trusted_schema=OFF")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def vehicles(self) -> list[dict]:
        with self.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    """SELECT vehicle_id,source_dataset,make,model,model_year,powertrain
                   FROM vehicle_registry ORDER BY vehicle_id"""
                )
            ]

    def capabilities(self, vehicle_id: str) -> list[dict]:
        with self.connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    """SELECT signal,unit,source_dataset,first_ts_replay_ns,last_ts_replay_ns,
                          expected_sampling_hz,observed_sampling_hz,sample_count,
                          missing_rate,coverage,provenance
                   FROM vehicle_capability WHERE vehicle_id=? ORDER BY signal""",
                    (vehicle_id,),
                )
            ]

    def samples(
        self,
        vehicle_id: str,
        signal: str,
        start_ns: int | None = None,
        end_ns: int | None = None,
        trip_ids: list[str] | None = None,
        limit: int = 100_000,
    ) -> list[dict]:
        if limit < 1 or limit > 100_000:
            raise ValueError("limit must be between 1 and 100000")
        clauses = ["vehicle_id=?", "signal=?"]
        params: list[object] = [vehicle_id, signal]
        if start_ns is not None:
            clauses.append("ts_replay_ns>=?")
            params.append(start_ns)
        if end_ns is not None:
            clauses.append("ts_replay_ns<=?")
            params.append(end_ns)
        if trip_ids is not None:
            if not trip_ids:
                return []
            clauses.append("trip_id IN (" + ",".join("?" for _ in trip_ids) + ")")
            params.extend(trip_ids)
        params.append(limit)
        sql = (
            """SELECT measurement_id,vehicle_id,trip_id,signal,unit,ts_source,
                        ts_source_seconds,ts_replay,ts_replay_ns,value,quality_flag,
                        provenance,source_dataset,source_file,source_row
                 FROM canonical_measurement WHERE """
            + " AND ".join(clauses)
            + " ORDER BY ts_replay_ns,trip_id,measurement_id LIMIT ?"
        )
        with self.connect() as con:
            if not con.execute(
                "SELECT 1 FROM vehicle_registry WHERE vehicle_id=?", (vehicle_id,)
            ).fetchone():
                raise LookupError(f"unknown vehicle: {vehicle_id}")
            if not con.execute(
                "SELECT 1 FROM vehicle_capability WHERE vehicle_id=? AND signal=?",
                (vehicle_id, signal),
            ).fetchone():
                raise LookupError(f"signal unavailable: {signal} for {vehicle_id}")
            return [dict(r) for r in con.execute(sql, params)]

    def events(
        self,
        vehicle_id: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
        event_type: str | None = None,
        include_synthetic: bool = False,
        limit: int = 10_000,
        trip_ids: list[str] | None = None,
    ) -> list[dict]:
        clauses = ["1=1"]
        params: list[object] = []
        for column, value in (("vehicle_id", vehicle_id), ("event_type", event_type)):
            if value is not None:
                clauses.append(column + "=?")
                params.append(value)
        if start_ns is not None:
            clauses.append("ts_replay_ns>=?")
            params.append(start_ns)
        if end_ns is not None:
            clauses.append("ts_replay_ns<=?")
            params.append(end_ns)
        if not include_synthetic:
            clauses.append("provenance='real'")
        if trip_ids is not None:
            if not trip_ids:
                return []
            clauses.append("trip_id IN (" + ",".join("?" for _ in trip_ids) + ")")
            params.extend(trip_ids)
        params.append(limit)
        sql = (
            """SELECT event_id,vehicle_id,trip_id,event_type,ts_source,ts_replay,
                        ts_replay_ns,provenance,injection_id,event_metadata_json
                 FROM overlay_event WHERE """
            + " AND ".join(clauses)
            + " ORDER BY ts_replay_ns,event_id LIMIT ?"
        )
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql, params)]

    def event_window(self, event_id: str) -> list[dict]:
        with self.connect() as con:
            rows = [
                dict(r)
                for r in con.execute(
                    """SELECT ew.event_id,ew.offset_seconds,ew.signal,ew.unit,ew.value,
                          ew.quality_flag,ew.provenance,ew.source_measurement_id,
                          COALESCE(cm.vehicle_id,oe.vehicle_id) AS vehicle_id,
                          COALESCE(cm.trip_id,oe.trip_id) AS trip_id,
                          COALESCE(cm.ts_replay,oe.ts_replay) AS ts_replay,
                          cm.source_file,cm.source_row
                   FROM event_window ew LEFT JOIN canonical_measurement cm
                     ON cm.measurement_id=ew.source_measurement_id
                   JOIN overlay_event oe ON oe.event_id=ew.event_id
                   WHERE ew.event_id=? ORDER BY ew.offset_seconds,ew.signal""",
                    (event_id,),
                )
            ]
            event = con.execute(
                "SELECT ts_replay_ns,injection_id FROM overlay_event WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not event or not event["injection_id"]:
                return rows
            overlays = [
                dict(r)
                for r in con.execute(
                    """SELECT overlay_sample_id,signal,unit,ts_replay_ns,value,
                              quality_flag,provenance
                       FROM overlay_sample WHERE injection_id=?
                       ORDER BY ts_replay_ns,overlay_sample_id""",
                    (event["injection_id"],),
                )
            ]
        anchor_ns = int(event["ts_replay_ns"])
        by_bucket: dict[tuple[int, str], list[dict]] = {}
        for sample in overlays:
            offset = round((sample["ts_replay_ns"] - anchor_ns) / 1e9)
            by_bucket.setdefault((offset, sample["signal"]), []).append(sample)
        for row in rows:
            if row["provenance"] != "real+overlay":
                continue
            samples = by_bucket.get((row["offset_seconds"], row["signal"]), [])
            if not samples:
                if row["provenance"] == "real+overlay":
                    row.update(
                        value=None,
                        quality_flag="contaminated_unrecoverable",
                        recovered_from_overlay=False,
                        overlay_sample_ids=[],
                    )
                continue
            values = [float(s["value"]) for s in samples if s["value"] is not None]
            row["value"] = sum(values) / len(values) if values else None
            row["unit"] = samples[0]["unit"]
            row["quality_flag"] = (
                "all_missing"
                if not values
                else "contains_missing_or_source_quality"
                if len(values) != len(samples)
                or any(s["quality_flag"] != "synthetic_injected" for s in samples)
                else "synthetic_injected"
            )
            row["provenance"] = "synthetic"
            row["recovered_from_overlay"] = True
            row["overlay_sample_ids"] = [s["overlay_sample_id"] for s in samples]
        return rows

    def overlay_signals_for_injections(self, injection_ids: list[str]) -> set[str]:
        if not injection_ids:
            return set()
        placeholders = ",".join("?" for _ in injection_ids)
        with self.connect() as con:
            return {
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT signal FROM overlay_sample WHERE injection_id IN ({placeholders})",
                    injection_ids,
                )
            }

    def resolve_evidence(self, table: str, record_id: str | int) -> dict | None:
        if table == "event_window":
            try:
                event_id, offset, signal = str(record_id).split("|", 2)
                offset = int(offset)
            except ValueError:
                return None
            with self.connect() as con:
                row = con.execute(
                    """SELECT ew.event_id,ew.offset_seconds,ew.signal,ew.unit,
                              ew.value,ew.quality_flag,ew.provenance,
                              COALESCE(cm.vehicle_id,oe.vehicle_id) AS vehicle_id,
                              COALESCE(cm.trip_id,oe.trip_id) AS trip_id,
                              COALESCE(cm.ts_replay,oe.ts_replay) AS ts_replay,
                              vr.source_dataset
                       FROM event_window ew LEFT JOIN canonical_measurement cm
                         ON cm.measurement_id=ew.source_measurement_id
                       JOIN overlay_event oe ON oe.event_id=ew.event_id
                       JOIN trip_registry tr ON tr.vehicle_id=oe.vehicle_id AND tr.trip_id=oe.trip_id
                       JOIN vehicle_registry vr ON vr.vehicle_id=tr.vehicle_id
                       WHERE ew.event_id=? AND ew.offset_seconds=? AND ew.signal=?""",
                    (event_id, offset, signal),
                ).fetchone()
                return dict(row) if row else None
        queries = {
            "canonical_measurement": (
                "measurement_id",
                "SELECT measurement_id,vehicle_id,trip_id,signal,unit,ts_replay,value,quality_flag,provenance,source_dataset,source_file,source_row FROM canonical_measurement WHERE measurement_id=?",
            ),
            "overlay_event": (
                "event_id",
                "SELECT event_id,vehicle_id,trip_id,event_type,ts_replay,provenance,injection_id FROM overlay_event WHERE event_id=?",
            ),
            "overlay_sample": (
                "overlay_sample_id",
                """SELECT os.overlay_sample_id,os.event_id,os.injection_id,os.signal,
                          os.unit,os.ts_replay_ns,os.value,os.quality_flag,os.provenance,
                          oe.vehicle_id,oe.trip_id,vr.source_dataset
                   FROM overlay_sample os JOIN overlay_event oe ON oe.event_id=os.event_id
                   JOIN vehicle_registry vr ON vr.vehicle_id=oe.vehicle_id
                   WHERE os.overlay_sample_id=?""",
            ),
        }
        if table not in queries:
            raise ValueError("evidence table is not resolvable")
        with self.connect() as con:
            row = con.execute(queries[table][1], (record_id,)).fetchone()
            return dict(row) if row else None
