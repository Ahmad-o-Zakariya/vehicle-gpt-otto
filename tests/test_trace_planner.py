import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pytest
from pydantic import ValidationError

from vehicle_gpt.evaluation.baselines.direct_sql import DirectSqlBaseline
from vehicle_gpt.evaluation.metrics import classification_metrics, latency_metrics
from vehicle_gpt.planner.inference import (
    CaseStudyDemoPlanner,
    LlamaCppPlanner,
)
from vehicle_gpt.planner.schema import ExecutionPlan, TimeRange
from vehicle_gpt.trace.claims import GradeInput, evidence_grade


def test_plan_schema_rejects_unregistered_intents_signals_and_engine_mismatch():
    with pytest.raises(ValidationError):
        ExecutionPlan(
            query_id="x", intent="trend", engine="events", vehicle_id="ved:455"
        )
    with pytest.raises(ValidationError):
        ExecutionPlan(
            query_id="x", intent="trend", engine="trends", signals=["vehicle.fake"]
        )
    with pytest.raises(ValidationError):
        TimeRange(start_ns=10, end_ns=1)


def test_demo_planner_covers_five_intents_as_development_fixture():
    planner = CaseStudyDemoPlanner()
    questions = [
        ("Why has driving range reduced over the last two weeks?", "ved:455"),
        ("When did fuel efficiency show its largest drop?", "ved:119"),
        ("Show all ADAS disengagement events from yesterday.", "openlka:clip:716581635d83a1fa"),
        ("What happened in the 60 seconds before the battery overheating warning in the BMW i3?", "tum_bmw_i3:bmw_i3"),
        ("Compare energy consumption between city and highway driving.", "ved:455"),
    ]
    plans = [planner.plan(q, selected_vehicle_id=v) for q, v in questions]
    assert [p.engine.value for p in plans] == [
        "trends",
        "unsupported",
        "events",
        "precursors",
        "unsupported",
    ]
    assert plans[0].required_coverage == ["two_week_history"]
    assert plans[2].time_range.wall_clock_claim
    assert plans[1].unsupported_reason and "fuel rate" in plans[1].unsupported_reason
    assert plans[4].unsupported_reason and "city/highway" in plans[4].unsupported_reason


def test_planner_endpoint_must_be_loopback():
    with pytest.raises(ValueError):
        LlamaCppPlanner("http://127.0.0.1.evil:8080/v1")


def test_synthetic_event_router_blocks_heldout_split():
    from vehicle_gpt.planner.router import DeterministicRouter

    plan = ExecutionPlan(
        query_id="heldout",
        intent="event_lookup",
        engine="events",
        vehicle_id="tum_bmw_i3:bmw_i3",
        event_type="diagnostic.warning",
        trip_ids=["TripB14"],
        include_synthetic=True,
    )
    with pytest.raises(ValueError, match="held-out"):
        DeterministicRouter().execute(plan)


def test_demo_thermal_plan_uses_development_trips_only():
    plan = CaseStudyDemoPlanner().plan(
        "What happened in the 60 seconds before the battery overheating warning in the BMW i3?"
    )
    assert plan.include_synthetic is True
    assert plan.trip_ids == ["TripB01", "TripB04", "TripB09", "TripB12"]
    assert plan.event_window_after_seconds == 0


def test_direct_sql_policy_rejects_non_select_writes_and_attaches(tmp_path):
    db = tmp_path / "fixture.sqlite"
    import sqlite3

    with sqlite3.connect(db) as con:
        con.execute("create table vehicle_registry(vehicle_id text)")
        con.execute("insert into vehicle_registry values('v1')")
    sql = DirectSqlBaseline(db)
    assert sql.execute("select vehicle_id from vehicle_registry")["rows"] == [
        {"vehicle_id": "v1"}
    ]
    for query in [
        "DELETE FROM vehicle_registry",
        "SELECT 1; ATTACH DATABASE ':memory:' AS gt",
        "SELECT * FROM gt.injection",
        "SELECT * FROM overlay_event",
    ]:
        with pytest.raises((ValueError, sqlite3.DatabaseError)):
            sql.execute(query)
    ground_truth = tmp_path / "ground_truth" / "labels.sqlite"
    ground_truth.parent.mkdir()
    with sqlite3.connect(ground_truth):
        pass
    with pytest.raises(ValueError, match="ground truth"):
        DirectSqlBaseline(ground_truth)
    from vehicle_gpt.evaluation.baselines.rag import LexicalRagBaseline

    with pytest.raises(ValueError, match="ground truth"):
        LexicalRagBaseline(ground_truth)


def test_evidence_grades_and_metrics_are_deterministic():
    assert evidence_grade(GradeInput()) == "E0"
    assert (
        evidence_grade(
            GradeInput(evidence_count=3, coverage="partial", provenance=["real"])
        )
        == "E1"
    )
    assert (
        evidence_grade(
            GradeInput(
                evidence_count=4,
                coverage="adequate",
                provenance=["real"],
                distinct_trips=3,
                distinct_signals=2,
                distinct_sources=2,
            )
        )
        == "E3"
    )
    assert (
        evidence_grade(
            GradeInput(
                evidence_count=1,
                coverage="conflicting",
                provenance=["real"],
                conflicting=True,
            )
        )
        == "E-"
    )
    assert classification_metrics(["yes", "no"], ["yes", "yes"])["accuracy"] == 0.5
    assert latency_metrics([3, 1, 2])["median_ms"] == 2
