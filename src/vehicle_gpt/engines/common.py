from __future__ import annotations

import hashlib
import time
from pathlib import Path

from vehicle_gpt.engines.models import EngineResult, EvidenceReference
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "data/processed/vehicle_gpt.sqlite"


def evidence(
    table: str,
    record_id: str | int,
    vehicle: str,
    trip: str | None,
    signal: str | None = None,
    timestamp: str | None = None,
    unit: str | None = None,
    provenance: str = "real",
    calculation: str | None = None,
    source_dataset: str | None = None,
):
    ref_id = hashlib.sha256(f"{table}:{record_id}".encode()).hexdigest()[:20]
    return EvidenceReference(
        evidence_id=ref_id,
        source_database="operational",
        source_table=table,
        record_id=record_id,
        vehicle_id=vehicle,
        trip_id=trip,
        source_dataset=source_dataset,
        signal=signal,
        timestamp=timestamp,
        unit=unit,
        provenance=provenance,
        calculation=calculation,
    )


def base_result(start: float, **kwargs) -> EngineResult:
    return EngineResult(
        execution_ms=round((time.perf_counter() - start) * 1000, 3), **kwargs
    )


def repository() -> VehicleRepository:
    return VehicleRepository(DB_PATH)


def ts_window(start_ns: int | None, end_ns: int | None):
    return (start_ns, end_ns) if start_ns is not None or end_ns is not None else None
