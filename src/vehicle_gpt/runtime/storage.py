from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pydantic import TypeAdapter

from vehicle_gpt.runtime.messages import RuntimeRecord

RECORD = TypeAdapter(RuntimeRecord)


class RuntimeStore:
    """Append-only local runtime SQLite; never points at the frozen data DB."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        if "processed" in self.path.parts or "releases" in self.path.parts:
            raise ValueError(
                "runtime storage must be outside frozen processed/release data"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS runtime_message (
                message_id TEXT PRIMARY KEY, message_type TEXT NOT NULL,
                vehicle_id TEXT NOT NULL, trip_id TEXT, protocol TEXT NOT NULL,
                source_timestamp TEXT NOT NULL, provenance TEXT NOT NULL,
                quality_flag TEXT NOT NULL, payload_json TEXT NOT NULL)""")

    def append(self, record: RuntimeRecord) -> None:
        valid = RECORD.validate_python(record)
        payload = valid.model_dump(mode="json")
        with sqlite3.connect(self.path) as con:
            con.execute("PRAGMA query_only=OFF")
            con.execute(
                """INSERT INTO runtime_message VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    valid.message_id,
                    valid.message_type,
                    valid.vehicle_id,
                    valid.trip_id,
                    valid.protocol.value,
                    valid.source_timestamp,
                    valid.provenance.value,
                    valid.quality_flag.value,
                    json.dumps(payload, separators=(",", ":")),
                ),
            )

    def count(self) -> int:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as con:
            con.execute("PRAGMA query_only=ON")
            return con.execute("SELECT count(*) FROM runtime_message").fetchone()[0]
