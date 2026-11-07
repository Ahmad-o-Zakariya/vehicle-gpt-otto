"""Run read-only operational engine and security smoke checks; never reads labels."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.engines.common import DB_PATH
from vehicle_gpt.engines.comparisons import ComparisonEngine
from vehicle_gpt.engines.events import EventEngine
from vehicle_gpt.engines.precursors import PrecursorEngine
from vehicle_gpt.engines.trends import TrendEngine
from vehicle_gpt.evaluation.baselines.direct_sql import DirectSqlBaseline
from vehicle_gpt.evaluation.baselines.rag import LexicalRagBaseline
from vehicle_gpt.planner.inference import CaseStudyDemoPlanner
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository


def main():
    repo = VehicleRepository(DB_PATH)
    with repo.connect() as con:
        query_only = con.execute("PRAGMA query_only").fetchone()[0]
        try:
            con.execute("CREATE TABLE validation_write_probe(x)")
        except sqlite3.DatabaseError:
            write_blocked = True
        else:
            write_blocked = False
    vehicle = "ved:119"
    capabilities = repo.capabilities(vehicle)
    signal = next(
        c["signal"] for c in capabilities if c["signal"] == "vehicle.fuel_rate"
    )
    samples = repo.samples(vehicle, signal, limit=100_000)
    trips = sorted({r["trip_id"] for r in samples if r["trip_id"]})
    groups = {"trip_a": trips[:1], "trip_b": trips[1:2]}
    events = repo.events(limit=10_000)
    selected = events[0] if events else None
    engine_rows = {}
    event_result = EventEngine().run(
        query_id="validation-events",
        vehicle_id=selected["vehicle_id"] if selected else vehicle,
        event_type=selected["event_type"] if selected else None,
    )
    trend_result = TrendEngine().run(
        query_id="validation-trend", vehicle_id=vehicle, signal=signal, min_samples=10
    )
    comparison_result = ComparisonEngine().run(
        query_id="validation-comparison",
        vehicle_id=vehicle,
        signal=signal,
        trip_groups=groups,
        min_samples=10,
    )
    energy_samples = repo.samples("ved:455", "battery.voltage", limit=100_000)
    energy_trips = sorted({r["trip_id"] for r in energy_samples if r["trip_id"]})
    energy_groups = {"trip_a": energy_trips[:1], "trip_b": energy_trips[1:2]}
    energy_result = ComparisonEngine().run(
        query_id="validation-energy-throughput",
        vehicle_id="ved:455",
        signal="battery.voltage",
        trip_groups=energy_groups,
        min_samples=1,
        metric="energy_throughput",
    )
    demo = CaseStudyDemoPlanner().plan(
        "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
        selected_vehicle_id="tum_bmw_i3:bmw_i3",
    )
    precursor_result = PrecursorEngine().compare_events(
        query_id="validation-precursors",
        event_ids=demo.event_ids,
        signals=demo.signals,
        include_synthetic=True,
        before_seconds=demo.event_window_before_seconds,
        after_seconds=demo.event_window_after_seconds,
    )
    for name, result in (
        ("event", event_result),
        ("trend", trend_result),
        ("comparison", comparison_result),
        ("energy_throughput", energy_result),
        ("precursor", precursor_result),
    ):
        engine_rows[name] = {
            "status": result.coverage.status,
            "engine": result.engine,
            "vehicle_id": result.vehicle_id,
            "trip_count": len(result.trip_ids),
            "evidence_count": len(result.evidence),
            "all_evidence_resolves": all(
                repo.resolve_evidence(e.source_table, e.record_id) is not None
                for e in result.evidence
                if e.source_table != "calculation"
            ),
            "provenance": result.provenance,
            "error_code": result.error_code,
            "limitations": result.limitations,
            "units": result.units,
            "result": result.result if name == "energy_throughput" else None,
        }
    engine_report = {
        "scope": "operational database only; ground-truth database not opened",
        "database_read_only": query_only == 1 and write_blocked,
        "real_event_rows_available": len(events),
        "trend_signal": signal,
        "comparison_trip_groups": groups,
        "energy_throughput_trip_groups": energy_groups,
        "engines": engine_rows,
        "notes": [
            "The precursor case explicitly opts into development synthetic events.",
            "Comparison groups are trip-to-trip means, not city/highway labels.",
            "Each engine was exercised against operational rows; precursor overlay rows are development fixtures.",
        ],
    }

    sql = DirectSqlBaseline(DB_PATH)
    sql_checks = {
        "select_count": sql.execute(
            "SELECT COUNT(*) AS vehicle_count FROM vehicle_registry"
        )
    }
    hostile = [
        "DELETE FROM vehicle_registry",
        "SELECT 1; ATTACH DATABASE ':memory:' AS gt",
        "SELECT * FROM gt.injection",
        "SELECT * FROM overlay_event",
        "PRAGMA writable_schema=ON",
    ]
    sql_checks["rejected_attempts"] = []
    for statement in hostile:
        try:
            sql.execute(statement)
        except (ValueError, sqlite3.DatabaseError) as exc:
            sql_checks["rejected_attempts"].append(
                {"sql": statement, "rejected": True, "error": type(exc).__name__}
            )
        else:
            sql_checks["rejected_attempts"].append(
                {"sql": statement, "rejected": False}
            )
    rag = LexicalRagBaseline(DB_PATH)
    rag_docs = rag.retrieve("battery overheating warning", 5)
    rag.close()
    security_report = {
        "scope": "read-only security smoke; no ground-truth connection attempted",
        "operational_repository_read_only": query_only == 1 and write_blocked,
        "direct_sql": sql_checks,
        "lexical_retrieval": {
            "method": "SQLite FTS5/BM25",
            "retrieved_count": len(rag_docs),
            "document_ids": [d["doc_id"] for d in rag_docs],
            "generation": "not run; local SLM unavailable",
        },
        "ground_truth_path_rejections": "covered by repository and baseline unit tests",
        "trace_adversarial_cases": "covered by pytest; see regression result",
    }
    out = ROOT / "artifacts/validation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "engine_validation_report.json").write_text(
        json.dumps(engine_report, indent=2) + "\n"
    )
    (out / "security_validation_report.json").write_text(
        json.dumps(security_report, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "database_read_only": engine_report["database_read_only"],
                "engines": {
                    k: {
                        "status": v["status"],
                        "evidence": v["evidence_count"],
                        "resolves": v["all_evidence_resolves"],
                    }
                    for k, v in engine_rows.items()
                },
                "rejected_sql_attempts": sum(
                    x["rejected"] for x in sql_checks["rejected_attempts"]
                ),
                "rag_docs": len(rag_docs),
                "energy_throughput_delta": energy_result.result.get(
                    "absolute_difference"
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
