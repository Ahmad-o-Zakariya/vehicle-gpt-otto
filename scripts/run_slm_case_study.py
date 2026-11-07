#!/usr/bin/env python3
"""Run the five cases through the live API and require genuine SLM mode."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = os.getenv("VEHICLEGPT_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("VEHICLEGPT_SLM_TIMEOUT_SECONDS", "90")) + 30
CASES = [
    (
        "driving_range_two_weeks",
        "Why has driving range reduced over the last two weeks?",
        "ved:455",
    ),
    (
        "fuel_efficiency_largest_drop",
        "When did fuel efficiency show its largest drop?",
        "ved:119",
    ),
    (
        "adas_yesterday",
        "Show all ADAS disengagement events from yesterday.",
        "openlka:clip:716581635d83a1fa",
    ),
    (
        "bmw_pre_warning",
        "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
        "tum_bmw_i3:bmw_i3",
    ),
    (
        "city_highway",
        "Compare energy consumption between city and highway driving.",
        "ved:455",
    ),
]


def main() -> int:
    health = requests.get(API + "/health", timeout=5).json()
    if health.get("planner_mode") != "llama.cpp local SLM":
        raise SystemExit(
            "Refusing to label demo/fixture results as SLM; start API without VEHICLEGPT_DEMO_MODE=1."
        )
    cases = []
    for case_id, question, vehicle_id in CASES:
        item = {
            "case": case_id,
            "question": question,
            "selected_vehicle_id": vehicle_id,
        }
        try:
            response = requests.post(
                API + "/query",
                json={"question": question, "vehicle_id": vehicle_id},
                timeout=TIMEOUT,
            )
            item["http_status"] = response.status_code
            if response.status_code != 200:
                item["error"] = response.json().get("detail", response.text)
            else:
                body = response.json()
                item.update(
                    {
                        "request_id": body["request_id"],
                        "planner_mode": body["planner_mode"],
                        "slm_raw_output": body.get("slm_raw_output"),
                        "semantic_query": body.get("semantic_query"),
                        "validated_plan": body["plan"],
                        "engine_result": body["engine_result"],
                        "evidence_references": body["answer"]["evidence"],
                        "evidence_grade": body["answer"]["overall_grade"],
                        "verification_passed": body["answer"]["grounded"],
                        "final_answer": body["answer"]["text"],
                        "latency_ms": body["latency_ms"],
                    }
                )
        except requests.RequestException as exc:
            item["http_status"] = None
            item["error"] = f"request failed: {exc}"
        cases.append(item)
    report = {
        "created_utc": datetime.now(UTC).isoformat(),
        "status": "passed"
        if len(cases) == 5
        and all(
            c.get("http_status") == 200 and c.get("verification_passed") for c in cases
        )
        else "incomplete",
        "planner_mode": "llama.cpp local SLM",
        "api": API,
        "scope": "five live case-study requests; raw SLM semantic output, deterministic resolution and TRACE result preserved separately",
        "cases": cases,
    }
    output = ROOT / "artifacts/evaluation/slm_case_study.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "cases": len(cases),
                "output": str(output.relative_to(ROOT)),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
