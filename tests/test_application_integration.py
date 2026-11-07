import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_gpt.api.app import _claim_answer
from vehicle_gpt.engines.common import DB_PATH
from vehicle_gpt.planner.inference import CaseStudyDemoPlanner
from vehicle_gpt.planner.router import DeterministicRouter
from vehicle_gpt.planner.schema import ExecutionPlan
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository
from vehicle_gpt.trace.verifier import TraceVerifier


def test_all_case_study_paths_are_grounded_and_fail_closed():
    planner = CaseStudyDemoPlanner()
    router = DeterministicRouter()
    questions = [
        (
            ("Why has driving range reduced over the last two weeks?", "ved:455"),
            "insufficient",
            "E0",
        ),
        (
            ("When did fuel efficiency show its largest drop?", "ved:119"),
            "unavailable",
            "E0",
        ),
        (
            (
                "Show all ADAS disengagement events from yesterday.",
                "openlka:clip:716581635d83a1fa",
            ),
            "insufficient",
            "E0",
        ),
        (
            (
                "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
                "tum_bmw_i3:bmw_i3",
            ),
            "partial",
            "E1",
        ),
        (
            ("Compare energy consumption between city and highway driving.", "ved:455"),
            "unavailable",
            "E0",
        ),
    ]
    for (question, vehicle_id), coverage, grade in questions:
        plan = planner.plan(question, selected_vehicle_id=vehicle_id)
        result = router.execute(plan)
        answer = _claim_answer(plan, result)
        assert answer.grounded is True
        assert answer.coverage_status == coverage
        assert answer.overall_grade == grade
        if "overheating" in question.lower():
            assert result.trip_ids == ["TripB01", "TripB04", "TripB09", "TripB12"]
            assert any(e.provenance == "synthetic" for e in answer.evidence)
            assert "synthetic" in answer.text.lower()


def test_verifier_rejects_corrupted_numeric_answer():
    plan = ExecutionPlan(
        query_id="numeric-trend",
        intent="trend",
        engine="trends",
        vehicle_id="ved:119",
        signals=["vehicle.fuel_rate"],
        aggregation="mean",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    claim = answer.claims[0].model_copy(
        update={"value": float(answer.claims[0].value) + 1.0}
    )
    corrupt = answer.model_copy(update={"claims": [claim]})
    verified = TraceVerifier(VehicleRepository(DB_PATH)).verify(corrupt, result)
    assert verified.grounded is False
    assert "rejected" in verified.text.lower()


def test_verifier_rejects_tampered_evidence_metadata():
    plan = ExecutionPlan(
        query_id="numeric-trend",
        intent="trend",
        engine="trends",
        vehicle_id="ved:119",
        signals=["vehicle.fuel_rate"],
        aggregation="mean",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    ref = answer.evidence[0].model_copy(update={"unit": "forged-unit"})
    tampered = answer.model_copy(update={"evidence": [ref, *answer.evidence[1:]]})
    verified = TraceVerifier(VehicleRepository(DB_PATH)).verify(tampered, result)
    assert verified.grounded is False
    assert "unit mismatch" in verified.text


def test_verifier_rejects_numeric_claim_without_calculation_reference():
    plan = ExecutionPlan(
        query_id="numeric-trend",
        intent="trend",
        engine="trends",
        vehicle_id="ved:119",
        signals=["vehicle.fuel_rate"],
        aggregation="mean",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    claim = answer.claims[0].model_copy(update={"calculation_ref": None})
    verified = TraceVerifier(VehicleRepository(DB_PATH)).verify(
        answer.model_copy(update={"claims": [claim]}), result
    )
    assert verified.grounded is False
    assert "calculation reference" in verified.text


def test_verifier_rejects_forged_claim_text_even_with_valid_calculation():
    plan = ExecutionPlan(
        query_id="numeric-trend",
        intent="trend",
        engine="trends",
        vehicle_id="ved:119",
        signals=["vehicle.fuel_rate"],
        aggregation="mean",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    claim = answer.claims[0].model_copy(
        update={"text": "Fuel rate averaged 6.7 L/h and the vehicle failed 99 times."}
    )
    verified = TraceVerifier(VehicleRepository(DB_PATH)).verify(
        answer.model_copy(update={"claims": [claim], "text": claim.text}),
        result,
    )
    assert verified.grounded is False
    assert "deterministic renderer" in verified.text


def test_verifier_rejects_synthetic_evidence_relabelled_as_real():
    plan = CaseStudyDemoPlanner().plan(
        "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
        selected_vehicle_id="tum_bmw_i3:bmw_i3",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    index = next(
        i for i, ref in enumerate(answer.evidence) if ref.provenance == "synthetic"
    )
    refs = list(answer.evidence)
    refs[index] = refs[index].model_copy(update={"provenance": "real"})
    verified = TraceVerifier(VehicleRepository(DB_PATH)).verify(
        answer.model_copy(update={"evidence": refs}), result
    )
    assert verified.grounded is False
    assert "provenance mismatch" in verified.text


def test_query_endpoint_honors_selected_vehicle():
    import os

    from vehicle_gpt.api.app import QueryRequest, query

    os.environ["VEHICLEGPT_DEMO_MODE"] = "1"
    try:
        response = query(
            QueryRequest(
                question="Why has driving range reduced over the last two weeks?",
                vehicle_id="ved:119",
            )
        )
    finally:
        os.environ.pop("VEHICLEGPT_DEMO_MODE", None)
    assert response.plan.vehicle_id == "ved:119"
    assert response.selected_vehicle_id == "ved:119"
    assert response.request_id == response.query_id


def test_wall_clock_query_fails_closed_without_signal_coverage_422():
    import os

    from vehicle_gpt.api.app import QueryRequest, query

    os.environ["VEHICLEGPT_DEMO_MODE"] = "1"
    try:
        response = query(
            QueryRequest(
                question="Show all ADAS disengagement events from yesterday.",
                vehicle_id="openlka:clip:716581635d83a1fa",
            )
        )
    finally:
        os.environ.pop("VEHICLEGPT_DEMO_MODE", None)
    assert response.answer.grounded is True
    assert response.answer.overall_grade == "E0"
    assert response.engine_result.error_code == "wall_clock_unsupported"


def test_explicit_vehicle_mismatch_is_fail_closed():
    import os

    from vehicle_gpt.api.app import QueryRequest, query

    os.environ["VEHICLEGPT_DEMO_MODE"] = "1"
    try:
        response = query(
            QueryRequest(
                question="What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
                vehicle_id="ved:455",
            )
        )
    finally:
        os.environ.pop("VEHICLEGPT_DEMO_MODE", None)
    assert response.plan.intent.value == "unsupported"
    assert "different vehicle" in response.engine_result.limitations[0]


def test_operational_event_list_defaults_to_real_observations_only():
    events = VehicleRepository(DB_PATH).events(limit=500)
    assert events
    assert all(event["provenance"] == "real" for event in events)


def test_frozen_mixed_t0_bucket_is_recovered_from_overlay_records_read_only():
    repo = VehicleRepository(DB_PATH)
    warning = next(
        event
        for event in repo.events(
            vehicle_id="tum_bmw_i3:bmw_i3",
            event_type="diagnostic.warning",
            include_synthetic=True,
            limit=100,
        )
        if event["trip_id"] == "TripB01"
    )
    t0 = next(
        row
        for row in repo.event_window(warning["event_id"])
        if row["offset_seconds"] == 0 and row["signal"] == "battery.temperature"
    )
    assert t0["recovered_from_overlay"] is True
    assert t0["provenance"] == "synthetic"
    assert t0["quality_flag"] == "synthetic_injected"
    assert len(t0["overlay_sample_ids"]) > 0
    refs = [
        repo.resolve_evidence("overlay_sample", item)
        for item in t0["overlay_sample_ids"]
    ]
    assert all(ref and ref["provenance"] == "synthetic" for ref in refs)
    assert all(ref["signal"] == "battery.temperature" for ref in refs)


def test_trace_verifies_recovered_overlay_sample_references():
    from vehicle_gpt.engines.precursors import PrecursorEngine
    from vehicle_gpt.planner.schema import ExecutionPlan

    repo = VehicleRepository(DB_PATH)
    warning = next(
        event
        for event in repo.events(
            vehicle_id="tum_bmw_i3:bmw_i3",
            event_type="diagnostic.warning",
            include_synthetic=True,
            limit=100,
        )
        if event["trip_id"] == "TripB01"
    )
    plan = ExecutionPlan(
        query_id="overlay-trace",
        intent="precursor",
        engine="precursors",
        vehicle_id="tum_bmw_i3:bmw_i3",
        event_ids=[warning["event_id"]],
        trip_ids=["TripB01"],
        signals=["battery.temperature"],
        include_synthetic=True,
        event_window_before_seconds=0,
        event_window_after_seconds=1,
    )
    result = PrecursorEngine().run(
        query_id=plan.query_id,
        event_id=warning["event_id"],
        signals=plan.signals,
        include_synthetic=True,
        before_seconds=0,
        after_seconds=1,
    )
    answer = _claim_answer(plan, result)
    assert answer.grounded is True
    assert any(ref.source_table == "overlay_sample" for ref in answer.evidence)


def test_precursor_before_window_is_strict_and_dropout_stays_missing():
    from vehicle_gpt.engines.precursors import PrecursorEngine

    repo = VehicleRepository(DB_PATH)
    warning = next(
        event
        for event in repo.events(
            vehicle_id="tum_bmw_i3:bmw_i3",
            event_type="diagnostic.warning",
            include_synthetic=True,
            limit=100,
        )
        if event["trip_id"] == "TripB01"
    )
    result = PrecursorEngine().run(
        query_id="strict-before",
        event_id=warning["event_id"],
        signals=["battery.temperature", "thermal.coolant_temperature_inlet"],
        include_synthetic=True,
        before_seconds=60,
        after_seconds=0,
    )
    assert result.result["event_anchor"]["offset_seconds"] == 0
    assert result.result["timeline"]
    assert all(row["offset_seconds"] < 0 for row in result.result["timeline"])
    coolant = [
        row
        for row in result.result["timeline"]
        if row["signal"] == "thermal.coolant_temperature_inlet"
    ]
    assert coolant and all(
        row["value"] is None for row in coolant if row["offset_seconds"] >= -60
    )
