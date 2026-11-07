from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    source_database: str
    source_table: Literal[
        "canonical_measurement",
        "overlay_event",
        "overlay_sample",
        "derived_1hz",
        "event_window",
        "calculation",
    ]
    record_id: str | int
    source_dataset: str | None = None
    vehicle_id: str
    trip_id: str | None = None
    signal: str | None = None
    timestamp: str | None = None
    interval: tuple[str | None, str | None] | None = None
    record_count: int | None = None
    unit: str | None = None
    provenance: str
    calculation: str | None = None
    transformation: str | None = None


class Coverage(BaseModel):
    status: Literal[
        "adequate", "partial", "insufficient", "unavailable", "invalid", "conflicting"
    ]
    available_rows: int = 0
    missing_rows: int = 0
    trips: list[str] = Field(default_factory=list)
    source_coverage: float | None = None
    sampling_median_seconds: float | None = None
    limitations: list[str] = Field(default_factory=list)


class EngineResult(BaseModel):
    engine: str
    engine_version: str = "1.0.0"
    query_id: str
    vehicle_id: str | None = None
    trip_ids: list[str] = Field(default_factory=list)
    time_range: tuple[int | None, int | None] | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    method: str
    evidence: list[EvidenceReference] = Field(default_factory=list)
    coverage: Coverage
    missing_data: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    execution_ms: float = 0
    error_code: str | None = None
