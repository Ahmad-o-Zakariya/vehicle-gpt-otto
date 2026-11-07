from __future__ import annotations

import logging
import os
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from vehicle_gpt.engines.common import repository
from vehicle_gpt.engines.models import EngineResult, EvidenceReference
from vehicle_gpt.planner.inference import (
    CaseStudyDemoPlanner,
    LlamaCppPlanner,
    PlannerError,
)
from vehicle_gpt.planner.router import DeterministicRouter
from vehicle_gpt.planner.schema import ExecutionPlan
from vehicle_gpt.planner.semantic_schema import SemanticQuery
from vehicle_gpt.trace.claims import Claim, GradeInput, TraceAnswer, evidence_grade
from vehicle_gpt.trace.coverage import CoverageChecker
from vehicle_gpt.trace.verifier import TraceVerifier

logging.basicConfig(level=os.getenv("VEHICLEGPT_LOG_LEVEL", "INFO"))
log = logging.getLogger("vehicle_gpt.api")
app = FastAPI(title="VehicleGPT local evidence API", version="0.2.0", docs_url="/docs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8501", "http://localhost:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    vehicle_id: str | None = Field(default=None, max_length=200)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: ExecutionPlan


class QueryResponse(BaseModel):
    request_id: str
    selected_vehicle_id: str | None
    query_id: str
    planner_mode: str
    semantic_query: SemanticQuery | None = None
    slm_raw_output: str | None = None
    plan: ExecutionPlan
    engine_result: EngineResult
    answer: TraceAnswer
    latency_ms: float


def _planner():
    if os.getenv("VEHICLEGPT_DEMO_MODE", "0") == "1":
        return CaseStudyDemoPlanner(), "deterministic_demo_fixture"
    return LlamaCppPlanner(), "llama.cpp local SLM"


def _claim_answer(plan: ExecutionPlan, result: EngineResult) -> TraceAnswer:
    refs = result.evidence
    grade = evidence_grade(
        GradeInput(
            evidence_count=len(refs),
            coverage=result.coverage.status,
            provenance=result.provenance,
            distinct_trips=len({r.trip_id for r in refs if r.trip_id}),
            distinct_signals=len({r.signal for r in refs if r.signal}),
            distinct_sources=len({r.source_dataset or r.source_database for r in refs}),
            conflicting=result.coverage.status == "conflicting",
        )
    )
    limitations = list(
        dict.fromkeys([*result.limitations, *result.coverage.limitations])
    )
    claims = []
    if not refs:
        message = (
            " ".join(limitations) or "No supporting operational evidence was found."
        )
        claims = [
            Claim(
                claim_id=plan.query_id + "-c0",
                claim_type="no_evidence",
                text="Insufficient evidence: " + message,
                value=None,
                evidence_refs=[],
                grade="E0",
                limitations=limitations,
            )
        ]
        grade = "E0"
    elif result.engine == "events" and "count" in result.result:
        count = int(result.result["count"])
        synth = sum(1 for e in refs if e.provenance == "synthetic")
        text = f"Found {count} matching event records."
        if synth:
            text += f" {synth} supporting references are synthetic overlay evidence."
        claims.append(
            Claim(
                claim_id=plan.query_id + "-c1",
                claim_type="event",
                text=text,
                value=count,
                units="events",
                evidence_refs=[e.evidence_id for e in refs],
                calculation_ref="result.count",
                grade=grade,
                limitations=limitations,
            )
        )
    elif result.engine == "comparisons" and result.result.get("groups"):
        for label, group in result.result["groups"].items():
            if group.get("mean") is None:
                continue
            group_refs = [
                r
                for r in refs
                if r.calculation == f"group:{label}"
                or r.calculation == f"result.groups.{label}.mean"
            ]
            unit = group.get("unit") or (group_refs[-1].unit if group_refs else None)
            value = float(group["mean"])
            claims.append(
                Claim(
                    claim_id=plan.query_id + "-" + label,
                    claim_type="comparison",
                    text=f"{label} group mean: {value:.6g} {unit} over {group['sample_count']} samples/trips.",
                    value=value,
                    units=unit,
                    evidence_refs=[r.evidence_id for r in group_refs],
                    calculation_ref=f"result.groups.{label}.mean",
                    grade=grade,
                    limitations=limitations,
                )
            )
    elif (
        result.engine == "trends"
        and "mean" in result.result
        and result.result.get("mean") is not None
    ):
        value = float(result.result["mean"])
        unit = refs[0].unit
        signal = plan.signals[0] if plan.signals else "signal"
        text = f"{signal} mean: {value:.6g} {unit}; {result.result['count']} valid samples."
        points = result.result.get("points", [])
        calc_ref = EvidenceReference(
            evidence_id=plan.query_id + "-calc-mean",
            source_database="operational",
            source_table="calculation",
            record_id=plan.query_id + ":result.mean",
            source_dataset=refs[0].source_dataset,
            vehicle_id=plan.vehicle_id,
            trip_id=refs[0].trip_id if len({r.trip_id for r in refs}) == 1 else None,
            signal=signal,
            interval=(
                (result.result["first_timestamp"], result.result["last_timestamp"])
                if points
                else None
            ),
            unit=unit,
            provenance="real",
            calculation="result.mean",
            transformation="arithmetic mean over all valid canonical samples; no interpolation",
            record_count=result.result["count"],
        )
        refs = [*refs, calc_ref]
        claims.append(
            Claim(
                claim_id=plan.query_id + "-c1",
                claim_type="numeric",
                text=text,
                value=value,
                units=unit,
                evidence_refs=[e.evidence_id for e in refs],
                calculation_ref="result.mean",
                grade=grade,
                limitations=limitations,
            )
        )
    elif "timeline" in result.result:
        num = len(result.result["timeline"])
        text = f"Retrieved {num} event-window samples around a {result.result['event']['event_type']} event; temporal association only, not causation."
        if "synthetic" in result.provenance:
            text += " Synthetic overlay evidence is present."
        claims.append(
            Claim(
                claim_id=plan.query_id + "-c1",
                claim_type="event",
                text=text,
                value=num,
                units="samples",
                evidence_refs=[e.evidence_id for e in refs],
                calculation_ref="result.timeline_count",
                grade=grade,
                limitations=limitations,
            )
        )
    else:
        text = "Supporting evidence was retrieved; no numeric summary is asserted."
        if "synthetic" in result.provenance:
            text += " Evidence includes synthetic overlays."
        claims.append(
            Claim(
                claim_id=plan.query_id + "-c1",
                claim_type="limitation",
                text=text,
                evidence_refs=[e.evidence_id for e in refs],
                grade=grade,
                limitations=limitations,
            )
        )
    # Construct prose solely from the claim texts; verifier checks it byte-for-byte.
    answer_text = " ".join(c.text for c in claims)
    response = TraceAnswer(
        query_id=plan.query_id,
        text=answer_text,
        claims=claims,
        evidence=refs,
        overall_grade=grade,
        coverage_status=result.coverage.status,
    )
    return TraceVerifier(repository()).verify(response, result)


def _execute(
    plan: ExecutionPlan,
    mode: str = "typed_plan",
    request_id: str | None = None,
    semantic_query: SemanticQuery | None = None,
    slm_raw_output: str | None = None,
) -> QueryResponse:
    start = time.perf_counter()
    repo = repository()
    if (
        plan.vehicle_id
        and plan.signals
        and not (plan.time_range and plan.time_range.wall_clock_claim)
    ):
        window = plan.time_range
        cov = CoverageChecker(repo).check(
            vehicle_id=plan.vehicle_id,
            signals=plan.signals,
            start_ns=window.start_ns if window else None,
            end_ns=window.end_ns if window else None,
            min_trips=1,
            include_synthetic=plan.include_synthetic,
            allowed_trip_ids=plan.trip_ids if plan.include_synthetic else None,
        )
        if cov.status == "unavailable" and (
            any(not ok for ok in cov.signals_available.values())
            or "unknown vehicle identity" in cov.reasons
        ):
            raise HTTPException(
                status_code=422,
                detail={"code": "signal_unavailable", "reasons": cov.reasons},
            )
    result = DeterministicRouter().execute(plan)
    if result.vehicle_id is None:
        result.vehicle_id = plan.vehicle_id
    answer = _claim_answer(plan, result)
    latency = (time.perf_counter() - start) * 1000
    log.info(
        "query=%s engine=%s coverage=%s grounded=%s latency_ms=%.2f",
        plan.query_id,
        plan.engine.value,
        result.coverage.status,
        answer.grounded,
        latency,
    )
    return QueryResponse(
        request_id=request_id or str(uuid4()),
        selected_vehicle_id=plan.vehicle_id,
        query_id=plan.query_id,
        planner_mode=mode,
        semantic_query=semantic_query,
        slm_raw_output=slm_raw_output,
        plan=plan,
        engine_result=result,
        answer=answer,
        latency_ms=round(latency, 3),
    )


@app.get("/health")
def health():
    try:
        repo = repository()
        vehicles = len(repo.vehicles())
        return {
            "status": "ok",
            "operational_database": "read_only",
            "vehicles": vehicles,
            "planner_endpoint": os.getenv(
                "VEHICLEGPT_LLAMACPP_URL", "http://127.0.0.1:8080/v1"
            ),
            "planner_mode": _planner()[1],
        }
    except Exception as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@app.get("/vehicles")
def vehicles():
    return repository().vehicles()


@app.get("/vehicles/{vehicle_id}/capabilities")
def capabilities(vehicle_id: str):
    rows = repository().capabilities(vehicle_id)
    if not rows:
        raise HTTPException(404, detail="unknown vehicle or no measured capabilities")
    return rows


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    request_id = str(uuid4())
    try:
        planner, mode = _planner()
        plan = planner.plan(
            request.question,
            selected_vehicle_id=request.vehicle_id,
            request_id=request_id,
            repo=repository(),
        )
    except PlannerError as exc:
        status = 503 if exc.code == "planner_unavailable" else 422
        raise HTTPException(
            status, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(
            422, detail={"code": "query_resolution_failed", "message": str(exc)}
        ) from exc
    try:
        return _execute(
            plan,
            mode,
            request_id=request_id,
            semantic_query=getattr(planner, "last_semantic", None),
            slm_raw_output=getattr(planner, "last_raw_output", None),
        )
    except (ValueError, LookupError) as exc:
        raise HTTPException(
            422, detail={"code": "query_execution_invalid", "message": str(exc)}
        ) from exc


@app.post("/execute-plan", response_model=QueryResponse)
def execute_plan(request: PlanRequest):
    try:
        request_id = str(uuid4())
        plan = request.plan.model_copy(update={"query_id": request_id})
        return _execute(plan, request_id=request_id)
    except (ValueError, LookupError) as exc:
        raise HTTPException(
            422, detail={"code": "invalid_plan", "message": str(exc)}
        ) from exc


@app.get("/events")
def events(vehicle_id: str | None = None, limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(422, detail="limit must be 1..1000")
    return repository().events(vehicle_id=vehicle_id, limit=limit)


@app.get("/history")
def history(vehicle_id: str, signal: str, limit: int = 2000):
    try:
        rows = repository().samples(vehicle_id, signal, limit=limit)
    except LookupError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    return rows


@app.get("/evidence/{table}/{record_id}")
def evidence_detail(table: str, record_id: str):
    try:
        row = repository().resolve_evidence(table, record_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(404, detail="evidence record not found")
    return row
