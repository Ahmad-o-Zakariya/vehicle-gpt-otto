from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

OPERATIONAL_TABLES = {
    "vehicle_registry",
    "trip_registry",
    "canonical_measurement",
    "signal_catalog",
    "vehicle_capability",
    "signal_coverage",
    "baseline_real_events",
    "overlay_event",
}
ALLOWED_FUNCTIONS = {
    "count",
    "min",
    "max",
    "sum",
    "avg",
    "abs",
    "round",
    "coalesce",
    "lower",
    "upper",
    "strftime",
    "date",
    "substr",
    "cast",
}


def generate_sql(
    question: str,
    *,
    url: str = "http://127.0.0.1:8080/v1/chat/completions",
    model: str = "qwen3.5-2b-q4_k_m",
    timeout: float = 20,
) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("SQL baseline can call only loopback llama.cpp")
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 500,
        "messages": [
            {
                "role": "system",
                "content": "Generate one read-only SELECT query using only tables in the provided schema. Never use ATTACH, PRAGMA, DDL, DML, comments, or multiple statements. Return SQL only.",
            },
            {"role": "user", "content": question},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read(500_000))
    sql = data["choices"][0]["message"]["content"].strip()
    if sql.startswith("```"):
        sql = sql.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return sql


class DirectSqlBaseline:
    def __init__(
        self, database: Path, row_limit: int = 1000, timeout_seconds: float = 1.0
    ):
        self.database = database.resolve()
        if "ground_truth" in self.database.parts:
            raise ValueError("direct-SQL baseline cannot open ground truth")
        self.row_limit = row_limit
        self.timeout_seconds = timeout_seconds

    def execute(self, sql: str) -> dict:
        normalized = sql.lstrip().lower()
        if not normalized.startswith(("select ", "with ")):
            raise ValueError("only SELECT or read-only WITH queries are accepted")
        if len(sql) > 20_000:
            raise ValueError("SQL exceeds 20 KB limit")
        uri = f"file:{self.database.as_posix()}?mode=ro"
        started = time.perf_counter()
        con = sqlite3.connect(uri, uri=True, timeout=1)
        con.row_factory = sqlite3.Row
        con.execute(
            "CREATE TEMP VIEW baseline_real_events AS SELECT event_id,vehicle_id,trip_id,event_type,ts_replay,provenance,event_metadata_json FROM main.overlay_event WHERE provenance='real'"
        )
        con.execute("PRAGMA query_only=ON")
        deadline = time.perf_counter() + self.timeout_seconds

        def authorizer(action, arg1, arg2, db_name, trigger):
            if action == sqlite3.SQLITE_SELECT or action == sqlite3.SQLITE_RECURSIVE:
                return sqlite3.SQLITE_OK
            if (
                action == sqlite3.SQLITE_READ
                and db_name in (None, "main", "temp")
                and arg1 in OPERATIONAL_TABLES
            ):
                if arg1 == "overlay_event" and trigger != "baseline_real_events":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            if (
                action == sqlite3.SQLITE_FUNCTION
                and (arg2 or arg1 or "").lower() in ALLOWED_FUNCTIONS
            ):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        con.set_authorizer(authorizer)
        con.set_progress_handler(
            lambda: 1 if time.perf_counter() > deadline else 0, 1000
        )
        try:
            cursor = con.execute(sql)
            rows = [dict(r) for r in cursor.fetchmany(self.row_limit + 1)]
            truncated = len(rows) > self.row_limit
            return {
                "sql": sql,
                "columns": [d[0] for d in cursor.description or []],
                "rows": rows[: self.row_limit],
                "truncated": truncated,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "status": "ok",
            }
        finally:
            con.close()
