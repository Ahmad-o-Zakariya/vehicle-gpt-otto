from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol as TypingProtocol
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import ValidationError

from vehicle_gpt.planner.resolver import DeterministicResolver
from vehicle_gpt.planner.schema import ExecutionPlan
from vehicle_gpt.planner.semantic_schema import (
    SemanticDomain,
    SemanticIntent,
    SemanticOperation,
    SemanticQuery,
    TemporalScope,
)
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository


class PlannerError(RuntimeError):
    def __init__(self, message: str, code: str = "planner_malformed"):
        super().__init__(message)
        self.code = code


class Planner(TypingProtocol):
    def plan(
        self,
        question: str,
        selected_vehicle_id: str | None = None,
        request_id: str | None = None,
        repo: VehicleRepository | None = None,
    ) -> ExecutionPlan: ...


def _semantic_prompt(question: str, vehicle_context: dict) -> str:
    examples = [
        {
            "question": "Why has driving range reduced over the last two weeks?",
            "semantic": {
                "intent": "trend",
                "domain": "driving_range",
                "operation": "trend_summary",
                "temporal_scope": "last_two_weeks",
            },
        },
        {
            "question": "When did fuel efficiency show its largest drop?",
            "semantic": {
                "intent": "trend",
                "domain": "fuel_consumption",
                "operation": "largest_drop",
                "temporal_scope": "unspecified",
            },
        },
        {
            "question": "Show ADAS disengagement events from yesterday.",
            "semantic": {
                "intent": "event_lookup",
                "domain": "adas",
                "operation": "event_lookup",
                "temporal_scope": "yesterday",
            },
        },
        {
            "question": "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
            "semantic": {
                "intent": "precursor",
                "domain": "battery_overheating",
                "operation": "precursor_analysis",
                "temporal_scope": "before_event",
            },
        },
        {
            "question": "Compare energy consumption between city and highway driving.",
            "semantic": {
                "intent": "comparison",
                "domain": "energy_comparison",
                "operation": "group_comparison",
                "temporal_scope": "unspecified",
            },
        },
    ]
    return (
        "Interpret the question into the supplied semantic JSON schema. Output concepts only. "
        "Do not output signal, event, trip, vehicle, query, table or database identifiers. "
        "Do not output SQL, code, tools, filters, or an availability decision. The resolver will check data.\n"
        f"Vehicle context: {json.dumps(vehicle_context, separators=(',', ':'))}\n"
        f"Examples: {json.dumps(examples, separators=(',', ':'))}\n"
        f"Question: {question}"
    )


def _vehicle_context(repo: VehicleRepository, selected_vehicle_id: str | None) -> dict:
    if not selected_vehicle_id:
        return {
            "selected_vehicle": None,
            "coverage_period": None,
            "available_domains": [],
        }
    vehicle = next(
        (v for v in repo.vehicles() if v["vehicle_id"] == selected_vehicle_id), None
    )
    if vehicle is None:
        return {
            "selected_vehicle": "unregistered selection",
            "coverage_period": None,
            "available_domains": [],
        }
    caps = repo.capabilities(selected_vehicle_id)
    signals = {c["signal"] for c in caps}
    domains = []
    if signals & {"battery.soc", "battery.current", "battery.voltage"}:
        domains.append("driving_range_history (no direct range/odometer measurement)")
    if {"vehicle.fuel_rate", "vehicle.speed"} <= signals:
        domains.append("fuel consumption measurements (no direct efficiency signal)")
    event_types = sorted(
        {
            e["event_type"]
            for e in repo.events(
                vehicle_id=selected_vehicle_id, include_synthetic=False
            )
            if e["event_type"].startswith("adas.")
        }
    )
    if event_types:
        domains.append("ADAS state-transition events")
    if (
        "battery.temperature" in signals
        and vehicle["model"]
        and "i3" in str(vehicle["model"]).casefold()
    ):
        domains.append("synthetic thermal warning demonstrations")
    stamps = [
        c.get(k)
        for c in caps
        for k in ("first_ts_replay_ns", "last_ts_replay_ns")
        if c.get(k) is not None
    ]
    if stamps:
        import datetime

        period = [
            datetime.datetime.fromtimestamp(int(x) / 1e9, datetime.UTC)
            .date()
            .isoformat()
            for x in (min(stamps), max(stamps))
        ]
    else:
        period = None
    display = " ".join(
        str(vehicle.get(k)) for k in ("make", "model", "model_year") if vehicle.get(k)
    )
    return {
        "selected_vehicle": display,
        "coverage_period": period,
        "available_domains": domains,
    }


class LlamaCppPlanner:
    """Loopback llama.cpp semantic extractor followed by deterministic resolution."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (
            base_url or os.getenv("VEHICLEGPT_LLAMACPP_URL", "http://127.0.0.1:8080/v1")
        ).rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("planner endpoint must be local loopback")
        try:
            configured_timeout = float(
                os.getenv("VEHICLEGPT_SLM_TIMEOUT_SECONDS", "90")
            )
        except ValueError as exc:
            raise ValueError("VEHICLEGPT_SLM_TIMEOUT_SECONDS must be numeric") from exc
        self.timeout = timeout if timeout is not None else configured_timeout
        if self.timeout <= 0 or self.timeout > 300:
            raise ValueError(
                "SLM timeout must be greater than 0 and at most 300 seconds"
            )
        self.last_semantic: SemanticQuery | None = None
        self.last_raw_output: str | None = None

    def extract_semantic(
        self, question: str, *, selected_vehicle_id: str | None, repo: VehicleRepository
    ) -> SemanticQuery:
        if not question.strip() or len(question) > 4000:
            raise PlannerError(
                "question must contain 1–4000 characters", "invalid_question"
            )
        body = {
            "model": os.getenv("VEHICLEGPT_MODEL_ID", "qwen3.5-2b-q4_k_m"),
            "messages": [
                {
                    "role": "system",
                    "content": "Return only JSON matching the semantic schema. Do not infer data availability.",
                },
                {
                    "role": "user",
                    "content": _semantic_prompt(
                        question, _vehicle_context(repo, selected_vehicle_id)
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 160,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "semantic_query",
                    "strict": True,
                    "schema": SemanticQuery.model_json_schema(),
                },
            },
        }
        for attempt in range(2):
            req = urllib.request.Request(
                self.base_url + "/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    payload = json.loads(response.read(1_000_000))
                content = payload["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict)
                    )
                semantic = SemanticQuery.model_validate_json(content)
                self.last_semantic = semantic
                self.last_raw_output = content
                return semantic
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise PlannerError(
                    f"local llama.cpp endpoint unavailable: {exc}",
                    "planner_unavailable",
                ) from exc
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                raise PlannerError(
                    f"malformed llama.cpp response: {exc}", "planner_malformed"
                ) from exc
            except (ValidationError, ValueError) as exc:
                if attempt:
                    raise PlannerError(
                        f"SLM semantic output failed strict validation: {str(exc)[:300]}",
                        "semantic_invalid",
                    ) from exc
                body["messages"].append(
                    {
                        "role": "user",
                        "content": "The prior output did not match the semantic schema. Return only a valid schema object for the same question.",
                    }
                )
        raise PlannerError("SLM semantic output invalid", "semantic_invalid")

    def plan(
        self,
        question: str,
        selected_vehicle_id: str | None = None,
        request_id: str | None = None,
        repo: VehicleRepository | None = None,
    ) -> ExecutionPlan:
        if repo is None:
            from vehicle_gpt.engines.common import DB_PATH

            repo = VehicleRepository(DB_PATH)
        semantic = self.extract_semantic(
            question, selected_vehicle_id=selected_vehicle_id, repo=repo
        )
        return DeterministicResolver(repo).resolve(
            semantic,
            question=question,
            selected_vehicle_id=selected_vehicle_id,
            query_id=request_id or str(uuid4()),
        )


class CaseStudyDemoPlanner:
    """Deterministic semantic fixtures; never an SLM and uses the same resolver."""

    def __init__(self):
        self.last_semantic: SemanticQuery | None = None
        self.last_raw_output: None = None

    def plan(
        self,
        question: str,
        selected_vehicle_id: str | None = None,
        request_id: str | None = None,
        repo: VehicleRepository | None = None,
    ) -> ExecutionPlan:
        text = question.casefold()
        if "range" in text:
            semantic = SemanticQuery(
                intent=SemanticIntent.TREND,
                domain=SemanticDomain.DRIVING_RANGE,
                operation=SemanticOperation.TREND_SUMMARY,
                temporal_scope=TemporalScope.LAST_TWO_WEEKS,
            )
        elif "fuel efficiency" in text or "fuel economy" in text:
            semantic = SemanticQuery(
                intent=SemanticIntent.TREND,
                domain=SemanticDomain.FUEL_CONSUMPTION,
                operation=SemanticOperation.LARGEST_DROP,
                temporal_scope=TemporalScope.UNSPECIFIED,
            )
        elif "adas" in text or "disengagement" in text:
            semantic = SemanticQuery(
                intent=SemanticIntent.EVENT_LOOKUP,
                domain=SemanticDomain.ADAS,
                operation=SemanticOperation.EVENT_LOOKUP,
                temporal_scope=TemporalScope.YESTERDAY
                if "yesterday" in text
                else TemporalScope.UNSPECIFIED,
            )
        elif "overheat" in text or "battery overheating" in text:
            semantic = SemanticQuery(
                intent=SemanticIntent.PRECURSOR,
                domain=SemanticDomain.BATTERY_OVERHEATING,
                operation=SemanticOperation.PRECURSOR_ANALYSIS,
                temporal_scope=TemporalScope.BEFORE_EVENT,
            )
        elif "city" in text and "highway" in text:
            semantic = SemanticQuery(
                intent=SemanticIntent.COMPARISON,
                domain=SemanticDomain.ENERGY_COMPARISON,
                operation=SemanticOperation.GROUP_COMPARISON,
                temporal_scope=TemporalScope.UNSPECIFIED,
            )
        else:
            semantic = SemanticQuery(
                intent=SemanticIntent.UNSUPPORTED,
                domain=SemanticDomain.UNKNOWN,
                operation=SemanticOperation.UNSUPPORTED,
            )
        self.last_semantic = semantic
        if repo is None:
            from vehicle_gpt.engines.common import DB_PATH

            repo = VehicleRepository(DB_PATH)
        return DeterministicResolver(repo).resolve(
            semantic,
            question=question,
            selected_vehicle_id=selected_vehicle_id,
            query_id=request_id or str(uuid4()),
        )
