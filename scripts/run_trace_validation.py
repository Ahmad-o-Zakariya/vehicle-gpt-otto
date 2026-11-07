"""Run adversarial TRACE checks against operational evidence without labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vehicle_gpt.api.app import _claim_answer
from vehicle_gpt.engines.common import DB_PATH
from vehicle_gpt.engines.models import Coverage
from vehicle_gpt.planner.inference import CaseStudyDemoPlanner
from vehicle_gpt.planner.router import DeterministicRouter
from vehicle_gpt.planner.schema import ExecutionPlan
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository
from vehicle_gpt.trace.claims import GradeInput, evidence_grade
from vehicle_gpt.trace.coverage import CoverageChecker
from vehicle_gpt.trace.verifier import TraceVerifier


def main():
    repo = VehicleRepository(DB_PATH)
    verifier = TraceVerifier(repo)
    plan = ExecutionPlan(
        query_id="trace-validation-trend",
        intent="trend",
        engine="trends",
        vehicle_id="ved:119",
        signals=["vehicle.fuel_rate"],
        aggregation="mean",
    )
    result = DeterministicRouter().execute(plan)
    answer = _claim_answer(plan, result)
    claim = answer.claims[0]

    def check(name, changed_answer, changed_result=result):
        response = verifier.verify(changed_answer, changed_result)
        return {
            "case": name,
            "rejected": not response.grounded,
            "reason": response.text[:500] if not response.grounded else "",
        }

    rows = [
        check("valid baseline", answer),
        check(
            "corrupted numeric value",
            answer.model_copy(
                update={
                    "claims": [
                        claim.model_copy(update={"value": float(claim.value) + 7})
                    ]
                }
            ),
        ),
        check(
            "numeric value without calculation reference",
            answer.model_copy(
                update={"claims": [claim.model_copy(update={"calculation_ref": None})]}
            ),
        ),
        check(
            "fake evidence id",
            answer.model_copy(
                update={
                    "claims": [claim.model_copy(update={"evidence_refs": ["fake"]})]
                }
            ),
        ),
        check(
            "removed evidence record",
            answer.model_copy(update={"evidence": answer.evidence[1:]}),
        ),
        check(
            "forged unit",
            answer.model_copy(
                update={
                    "evidence": [
                        answer.evidence[0].model_copy(update={"unit": "forged"}),
                        *answer.evidence[1:],
                    ]
                }
            ),
        ),
        check(
            "wrong vehicle identity",
            answer.model_copy(
                update={
                    "evidence": [
                        answer.evidence[0].model_copy(update={"vehicle_id": "fake"}),
                        *answer.evidence[1:],
                    ]
                }
            ),
        ),
        check(
            "wrong evidence timestamp",
            answer.model_copy(
                update={
                    "evidence": [
                        answer.evidence[0].model_copy(
                            update={"timestamp": "1900-01-01"}
                        ),
                        *answer.evidence[1:],
                    ]
                }
            ),
        ),
        check(
            "unsupported causal wording",
            answer.model_copy(
                update={
                    "text": "The signal caused the vehicle failure.",
                    "claims": [
                        claim.model_copy(
                            update={"text": "The signal caused the vehicle failure."}
                        )
                    ],
                }
            ),
        ),
        check(
            "contradictory evidence grade",
            answer,
            result.model_copy(update={"coverage": Coverage(status="conflicting")}),
        ),
    ]

    thermal_plan = CaseStudyDemoPlanner().plan(
        "What happened in the 60 seconds before the battery overheating warning in the BMW i3?",
        selected_vehicle_id="tum_bmw_i3:bmw_i3",
    )
    thermal_result = DeterministicRouter().execute(thermal_plan)
    thermal_answer = _claim_answer(thermal_plan, thermal_result)
    synth_index = next(
        i
        for i, ref in enumerate(thermal_answer.evidence)
        if ref.provenance == "synthetic"
    )
    relabelled = list(thermal_answer.evidence)
    relabelled[synth_index] = relabelled[synth_index].model_copy(
        update={"provenance": "real"}
    )
    rows.append(
        check(
            "synthetic relabelled as real",
            thermal_answer.model_copy(update={"evidence": relabelled}),
            thermal_result,
        )
    )

    grades = {}
    fixtures = {
        "E0": GradeInput(),
        "E1": GradeInput(evidence_count=1, coverage="partial", provenance=["real"]),
        "E2": GradeInput(evidence_count=1, coverage="adequate", provenance=["real"]),
        "E3": GradeInput(
            evidence_count=4,
            coverage="adequate",
            provenance=["real"],
            distinct_trips=3,
            distinct_signals=2,
            distinct_sources=2,
        ),
        "E-": GradeInput(evidence_count=1, coverage="conflicting", provenance=["real"]),
    }
    for expected, fixture in fixtures.items():
        grades[expected] = evidence_grade(fixture)
    coverage = CoverageChecker(repo).check(
        vehicle_id="ved:455", signals=["vehicle.signal_not_registered"]
    )
    report = {
        "scope": "TRACE claims and operational metadata only; ground-truth database not opened",
        "grade_rules": grades,
        "coverage_missing_signal": {
            "status": coverage.status,
            "signals_available": coverage.signals_available,
        },
        "adversarial_cases": rows,
        "passed": grades == {g: g for g in fixtures}
        and coverage.status == "unavailable"
        and all(row["rejected"] for row in rows if row["case"] != "valid baseline")
        and next(row for row in rows if row["case"] == "valid baseline")["rejected"]
        is False,
    }
    destination = ROOT / "artifacts/validation/trace_validation_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "grades": grades,
                "cases": {row["case"]: row["rejected"] for row in rows},
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
