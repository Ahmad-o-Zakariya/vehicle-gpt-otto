from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


class LexicalRagBaseline:
    """SQLite FTS5/BM25 lexical retrieval; deliberately not dense-vector RAG."""

    def __init__(self, database: Path | None = None):
        if database is not None and "ground_truth" in database.resolve().parts:
            raise ValueError("lexical retrieval cannot open ground truth")
        self.con = sqlite3.connect(":memory:")
        self.con.execute(
            "CREATE VIRTUAL TABLE docs USING fts5(doc_id UNINDEXED, kind UNINDEXED, text, tokenize='unicode61')"
        )
        signal_data = yaml.safe_load((ROOT / "configs/signals.yaml").read_text())[
            "signals"
        ]
        self.con.executemany(
            "INSERT INTO docs VALUES(?,?,?)",
            [
                (
                    f"signal:{name}",
                    "signal",
                    f"{name} {spec.get('description', '')} unit {spec.get('unit', '')} source fields",
                )
                for name, spec in signal_data.items()
            ],
        )
        docs = ROOT / "docs"
        allowed_docs = {
            "DATA_DICTIONARY.md",
            "SIGNAL_CATALOGUE.md",
            "DATASET_ARCHITECTURE.md",
            "derived_method.md",
            "can_mapping.md",
            "dataset_inventory.md",
            "capability_coverage.md",
        }
        for path in sorted(docs.glob("*.md")):
            if path.name not in allowed_docs:
                continue
            self.con.execute(
                "INSERT INTO docs VALUES(?,?,?)",
                (
                    f"doc:{path.name}",
                    "documentation",
                    path.read_text(errors="replace")[:500_000],
                ),
            )
        if database:
            uri = f"file:{database.resolve().as_posix()}?mode=ro"
            src = sqlite3.connect(uri, uri=True)
            try:
                rows = src.execute(
                    "SELECT event_id,event_type,event_metadata_json,provenance FROM overlay_event WHERE provenance='real' ORDER BY ts_replay_ns LIMIT 1000"
                )
                self.con.executemany(
                    "INSERT INTO docs VALUES(?,?,?)",
                    [
                        (f"event:{r[0]}", "event", f"{r[1]} {r[2]} provenance {r[3]}")
                        for r in rows
                    ],
                )
            finally:
                src.close()

    def retrieve(self, query: str, limit: int = 5) -> list[dict]:
        words = re.findall(r"[\w.]+", query.lower())
        if not words:
            return []
        match = " OR ".join('"' + w.replace('"', "") + '"' for w in words[:32])
        return [
            dict(zip(("doc_id", "kind", "text", "bm25"), r))
            for r in self.con.execute(
                "SELECT doc_id,kind,substr(text,1,1200),bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
                (match, limit),
            )
        ]

    def close(self):
        self.con.close()
