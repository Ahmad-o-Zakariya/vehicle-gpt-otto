import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vehicle_gpt.engines.common import DB_PATH
from vehicle_gpt.planner.inference import LlamaCppPlanner, PlannerError
from vehicle_gpt.planner.resolver import DeterministicResolver
from vehicle_gpt.planner.semantic_schema import (
    SemanticDomain,
    SemanticIntent,
    SemanticOperation,
    SemanticQuery,
    TemporalScope,
)
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository

REPO = VehicleRepository(DB_PATH)


def semantic(intent, domain, operation, **kwargs):
    intent = SemanticIntent(intent) if isinstance(intent, str) else intent
    domain = SemanticDomain(domain) if isinstance(domain, str) else domain
    operation = (
        SemanticOperation(operation) if isinstance(operation, str) else operation
    )
    if "temporal_scope" in kwargs and isinstance(kwargs["temporal_scope"], str):
        kwargs["temporal_scope"] = TemporalScope(kwargs["temporal_scope"])
    kwargs.setdefault("temporal_scope", TemporalScope.UNSPECIFIED)
    return SemanticQuery(intent=intent, domain=domain, operation=operation, **kwargs)


def test_semantic_schema_is_small_strict_and_has_no_database_identifiers():
    query = semantic("trend", "driving_range", "trend_summary")
    assert query.temporal_scope is TemporalScope.UNSPECIFIED
    assert {"signal_id", "event_id", "trip_id", "vehicle_id", "query_id"}.isdisjoint(
        SemanticQuery.model_fields
    )
    with pytest.raises(ValidationError):
        SemanticQuery.model_validate(
            {
                "intent": "trend",
                "domain": "made_up",
                "operation": "trend_summary",
                "temporal_scope": "unspecified",
            }
        )
    with pytest.raises(ValidationError):
        SemanticQuery.model_validate(
            {
                "intent": "trend",
                "domain": "driving_range",
                "operation": "trend_summary",
                "temporal_scope": "unspecified",
                "signal_id": "battery.soc",
            }
        )


class FakeResponse:
    def __init__(self, content):
        self.content = json.dumps(
            {"choices": [{"message": {"content": content}}]}
        ).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self.content


def test_llama_planner_requests_semantics_with_selected_vehicle_context():
    answer = json.dumps(
        {
            "intent": "trend",
            "domain": "driving_range",
            "operation": "trend_summary",
            "temporal_scope": "last_two_weeks",
        }
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse(answer)

    planner = LlamaCppPlanner(timeout=2)
    with patch("urllib.request.urlopen", fake_urlopen):
        result = planner.extract_semantic(
            "Why has driving range reduced over the last two weeks?",
            selected_vehicle_id="ved:455",
            repo=REPO,
        )
    assert result.domain.value == "driving_range"
    prompt = captured["body"]["messages"][1]["content"]
    assert "Nissan" in prompt or "Leaf" in prompt
    assert "2017-11-05" in prompt or "2018-11-05" in prompt
    assert "Do not output signal" in prompt
    assert captured["timeout"] == 2


def test_llama_planner_invalid_semantic_json_is_controlled_and_bounded():
    calls = 0

    def fake_urlopen(_request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse(
            '{"intent":"trend","domain":"invalid","operation":"trend_summary"}'
        )

    with (
        patch("urllib.request.urlopen", fake_urlopen),
        pytest.raises(PlannerError) as error,
    ):
        LlamaCppPlanner(timeout=2).extract_semantic(
            "show a trend", selected_vehicle_id="ved:455", repo=REPO
        )
    assert error.value.code == "semantic_invalid"
    assert calls == 2


def test_resolver_five_case_families_and_fail_closed_boundaries():
    resolver = DeterministicResolver(REPO)
    cases = [
        (
            semantic(
                "trend",
                "driving_range",
                "trend_summary",
                temporal_scope="last_two_weeks",
            ),
            "Why has driving range reduced over the last two weeks?",
            "ved:455",
            "trends",
        ),
        (
            semantic("trend", "fuel_consumption", "largest_drop"),
            "When did fuel efficiency show its largest drop?",
            "ved:119",
            "unsupported",
        ),
        (
            semantic(
                "event_lookup", "adas", "event_lookup", temporal_scope="yesterday"
            ),
            "Show all ADAS disengagement events from yesterday.",
            "openlka:clip:716581635d83a1fa",
            "events",
        ),
        (
            semantic(
                "precursor",
                "battery_overheating",
                "precursor_analysis",
                temporal_scope="before_event",
            ),
            "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
            "tum_bmw_i3:bmw_i3",
            "precursors",
        ),
        (
            semantic("comparison", "energy_comparison", "group_comparison"),
            "Compare energy consumption between city and highway driving.",
            "ved:455",
            "unsupported",
        ),
    ]
    plans = [
        resolver.resolve(s, question=q, selected_vehicle_id=v) for s, q, v, _ in cases
    ]
    assert [p.engine.value for p in plans] == [engine for *_, engine in cases]
    assert all(p.query_id for p in plans)
    assert plans[0].required_coverage == ["two_week_history"]
    assert plans[1].unsupported_reason and "fuel rate" in plans[1].unsupported_reason
    assert plans[2].time_range and plans[2].time_range.wall_clock_claim
    thermal = plans[3]
    assert thermal.trip_ids == ["TripB01", "TripB04", "TripB09", "TripB12"]
    assert "TripB14" not in thermal.trip_ids
    assert (
        thermal.event_window_before_seconds == 60
        and thermal.event_window_after_seconds == 0
    )
    assert "thermal.coolant_pump_duty" in thermal.signals
    assert set(thermal.signals) <= {
        r["signal"] for r in REPO.capabilities(thermal.vehicle_id)
    } | REPO.overlay_signals_for_injections(
        [
            "inj:thermal:tripb01",
            "inj:thermal:tripb04",
            "inj:thermal:tripb09",
            "inj:thermal:tripb12",
        ]
    )
    assert (
        plans[4].unsupported_reason
        and "verified city/highway" in plans[4].unsupported_reason
    )


def test_resolver_vehicle_mismatch_unknown_and_missing_capability():
    resolver = DeterministicResolver(REPO)
    thermal = semantic(
        "precursor",
        "battery_overheating",
        "precursor_analysis",
        temporal_scope="before_event",
    )
    mismatch = resolver.resolve(
        thermal, question="BMW i3 overheating warning", selected_vehicle_id="ved:455"
    )
    assert mismatch.intent.value == "unsupported"
    assert "different vehicle" in mismatch.unsupported_reason
    unknown = resolver.resolve(
        semantic("trend", "driving_range", "trend_summary"),
        question="range trend",
        selected_vehicle_id="unknown",
    )
    assert unknown.intent.value == "unsupported"
    missing = resolver.resolve(
        semantic("trend", "fuel_consumption", "largest_drop"),
        question="fuel economy",
        selected_vehicle_id="ved:455",
    )
    assert missing.intent.value == "unsupported"


def test_unambiguous_vehicle_can_be_resolved_without_selection():
    result = DeterministicResolver(REPO).resolve(
        semantic("precursor", "battery_overheating", "precursor_analysis"),
        question="What happened before the battery overheating warning in the BMW i3?",
        selected_vehicle_id=None,
    )
    assert result.vehicle_id == "tum_bmw_i3:bmw_i3"


def test_optional_real_slm_integration():
    if os.getenv("VEHICLEGPT_RUN_SLM_INTEGRATION") != "1":
        pytest.skip("set VEHICLEGPT_RUN_SLM_INTEGRATION=1 to call local llama.cpp")
    plan = LlamaCppPlanner().plan(
        "Why has driving range reduced over the last two weeks?",
        selected_vehicle_id="ved:455",
        repo=REPO,
    )
    assert plan.engine.value == "trends"
    assert plan.query_id
