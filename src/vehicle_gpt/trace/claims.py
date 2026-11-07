from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vehicle_gpt.engines.models import EvidenceReference


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str
    claim_type: Literal[
        "numeric", "event", "trend", "comparison", "limitation", "no_evidence"
    ]
    text: str
    value: float | int | str | bool | None = None
    units: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    calculation_ref: str | None = None
    grade: Literal["E0", "E1", "E2", "E3", "E-"]
    limitations: list[str] = Field(default_factory=list)
    verifier_status: Literal["pending", "verified", "rejected"] = "pending"


class TraceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    text: str
    claims: list[Claim]
    evidence: list[EvidenceReference]
    overall_grade: Literal["E0", "E1", "E2", "E3", "E-"]
    coverage_status: str
    grounded: bool = False


class GradeInput(BaseModel):
    evidence_count: int = 0
    coverage: str = "insufficient"
    provenance: list[str] = Field(default_factory=list)
    distinct_trips: int = 0
    distinct_signals: int = 0
    distinct_sources: int = 0
    conflicting: bool = False


def evidence_grade(data: GradeInput) -> str:
    if data.conflicting or data.coverage == "conflicting":
        return "E-"
    if data.evidence_count == 0:
        return "E0"
    if data.coverage != "adequate" or any(p != "real" for p in data.provenance):
        return "E1"
    if (
        data.distinct_trips >= 3
        and data.distinct_signals >= 2
        and data.distinct_sources >= 2
    ):
        return "E3"
    return "E2"


def render_claims(claims: list[Claim]) -> str:
    """Only verified claim text is rendered; the SLM cannot add free prose."""
    verified = [c.text for c in claims if c.verifier_status == "verified"]
    return (
        " ".join(verified)
        if verified
        else "No verified claim is available from the selected evidence."
    )
