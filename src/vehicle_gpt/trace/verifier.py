from __future__ import annotations

import re
from typing import Any

from vehicle_gpt.engines.models import EngineResult
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository
from vehicle_gpt.trace.claims import (
    Claim,
    GradeInput,
    TraceAnswer,
    evidence_grade,
    render_claims,
)

CAUSAL = re.compile(
    r"\b(caused|causes|causing|resulted in|due to|because of)\b", re.IGNORECASE
)


def _path(data: dict[str, Any], path: str | None):
    if not path:
        return None
    value: Any = data
    for token in path.split("."):
        if isinstance(value, dict) and token in value:
            value = value[token]
        else:
            return None
    return value


def _expected_claim_text(claim: Claim, engine: EngineResult, refs: list):
    if not refs:
        if claim.claim_type == "no_evidence":
            limits = list(
                dict.fromkeys([*engine.limitations, *engine.coverage.limitations])
            )
            message = (
                " ".join(limits) or "No supporting operational evidence was found."
            )
            return "Insufficient evidence: " + message
        return None
    if engine.engine == "events" and "count" in engine.result:
        count = int(engine.result["count"])
        synthetic = sum(ref.provenance == "synthetic" for ref in engine.evidence)
        text = f"Found {count} matching event records."
        if synthetic:
            text += (
                f" {synthetic} supporting references are synthetic overlay evidence."
            )
        return text
    if engine.engine == "comparisons" and engine.result.get("groups"):
        calc_ref = claim.calculation_ref or ""
        if not calc_ref.startswith("result.groups.") or not calc_ref.endswith(".mean"):
            return None
        label = calc_ref.removeprefix("result.groups.").removesuffix(".mean")
        group = engine.result["groups"].get(label)
        if group is None or group.get("mean") is None:
            return None
        return f"{label} group mean: {float(group['mean']):.6g} {group.get('unit')} over {group['sample_count']} samples/trips."
    if engine.engine == "trends" and engine.result.get("mean") is not None:
        signal_ref = next((ref for ref in refs if ref.signal), None)
        unit_ref = next((ref for ref in refs if ref.unit), None)
        if signal_ref is None or unit_ref is None:
            return None
        return f"{signal_ref.signal} mean: {float(engine.result['mean']):.6g} {unit_ref.unit}; {engine.result['count']} valid samples."
    if "timeline" in engine.result:
        text = f"Retrieved {len(engine.result['timeline'])} event-window samples around a {engine.result['event']['event_type']} event; temporal association only, not causation."
        if "synthetic" in engine.provenance:
            text += " Synthetic overlay evidence is present."
        return text
    text = "Supporting evidence was retrieved; no numeric summary is asserted."
    if "synthetic" in engine.provenance:
        text += " Evidence includes synthetic overlays."
    return text


class TraceVerifier:
    def __init__(self, repo: VehicleRepository):
        self.repo = repo

    def verify(self, answer: TraceAnswer, engine: EngineResult) -> TraceAnswer:
        ref_by_id = {r.evidence_id: r for r in answer.evidence}
        issues = []
        if len(ref_by_id) != len(answer.evidence):
            issues.append("duplicate evidence IDs are not allowed")
        cited_ids = {
            ref_id for claim in answer.claims for ref_id in claim.evidence_refs
        }
        if set(ref_by_id) - cited_ids:
            issues.append("uncited evidence references are not allowed")
        verified = []
        for claim in answer.claims:
            claim_issues = []
            if (
                claim.claim_type in {"numeric", "event", "trend", "comparison"}
                and not claim.evidence_refs
            ):
                claim_issues.append(f"{claim.claim_id}: factual claim has no evidence")
            if (
                isinstance(claim.value, (int, float))
                and not isinstance(claim.value, bool)
                and not claim.calculation_ref
            ):
                claim_issues.append(
                    f"{claim.claim_id}: numeric value has no calculation reference"
                )
            refs = [ref_by_id.get(i) for i in claim.evidence_refs]
            if any(r is None for r in refs):
                claim_issues.append(f"{claim.claim_id}: evidence reference missing")
            resolved = []
            for r in refs:
                if r is None:
                    continue
                if r.source_table == "calculation":
                    if r.source_database != "operational":
                        claim_issues.append(
                            f"{claim.claim_id}: calculation source is not operational"
                        )
                    row = {
                        "vehicle_id": r.vehicle_id,
                        "trip_id": r.trip_id,
                        "provenance": r.provenance,
                        "source_dataset": r.source_dataset,
                    }
                    calc_value = _path(engine.model_dump(), r.calculation)
                    if (
                        r.record_id != f"{engine.query_id}:{r.calculation}"
                        or calc_value is None
                    ):
                        row = None
                else:
                    if r.source_database != "operational":
                        claim_issues.append(
                            f"{claim.claim_id}: evidence source is not operational"
                        )
                    row = self.repo.resolve_evidence(r.source_table, r.record_id)
                if row is None:
                    claim_issues.append(
                        f"{claim.claim_id}: evidence record does not resolve"
                    )
                else:
                    if row.get("vehicle_id") != r.vehicle_id:
                        claim_issues.append(
                            f"{claim.claim_id}: vehicle identity mismatch"
                        )
                    if r.trip_id is not None and row.get("trip_id") != r.trip_id:
                        claim_issues.append(f"{claim.claim_id}: trip identity mismatch")
                    if row.get("provenance") != r.provenance:
                        claim_issues.append(f"{claim.claim_id}: provenance mismatch")
                    if (
                        r.source_dataset
                        and row.get("source_dataset") != r.source_dataset
                    ):
                        claim_issues.append(
                            f"{claim.claim_id}: source dataset mismatch"
                        )
                    if r.source_table != "calculation":
                        if r.signal is not None and row.get("signal") != r.signal:
                            claim_issues.append(
                                f"{claim.claim_id}: signal identity mismatch"
                            )
                        if r.unit is not None and row.get("unit") != r.unit:
                            claim_issues.append(
                                f"{claim.claim_id}: evidence unit mismatch"
                            )
                        if (
                            r.timestamp is not None
                            and row.get("ts_replay") != r.timestamp
                        ):
                            claim_issues.append(
                                f"{claim.claim_id}: evidence timestamp mismatch"
                            )
                    resolved.append(r)
            if claim.calculation_ref:
                expected = _path(engine.model_dump(), claim.calculation_ref)
                if expected is None:
                    claim_issues.append(f"{claim.claim_id}: calculation is absent")
                elif isinstance(claim.value, (int, float)) and not isinstance(
                    claim.value, bool
                ):
                    if (
                        not isinstance(expected, (int, float))
                        or abs(float(expected) - float(claim.value)) > 1e-9
                    ):
                        claim_issues.append(f"{claim.claim_id}: numeric value mismatch")
                elif claim.value != expected:
                    claim_issues.append(f"{claim.claim_id}: value mismatch")
            expected_text = _expected_claim_text(
                claim, engine, [ref for ref in refs if ref is not None]
            )
            if expected_text is not None and claim.text != expected_text:
                claim_issues.append(
                    f"{claim.claim_id}: claim text does not match deterministic renderer"
                )
            if (
                claim.claim_type == "numeric"
                and claim.units
                and refs
                and not any(r and r.unit == claim.units for r in refs)
            ):
                claim_issues.append(f"{claim.claim_id}: unsupported unit")
            if CAUSAL.search(claim.text):
                claim_issues.append(
                    f"{claim.claim_id}: causal interpretation is unsupported"
                )
            if engine.vehicle_id and any(
                r.vehicle_id != engine.vehicle_id for r in resolved
            ):
                claim_issues.append(
                    f"{claim.claim_id}: evidence belongs to another vehicle"
                )
            if engine.coverage.status == "conflicting" and claim.grade != "E-":
                claim_issues.append(
                    f"{claim.claim_id}: conflicting evidence requires E-"
                )
            issues.extend(claim_issues)
            if (
                any(r and r.provenance == "synthetic" for r in refs)
                and claim.claim_type not in {"limitation", "no_evidence"}
                and not re.search(r"synthetic|simulated", claim.text, re.IGNORECASE)
            ):
                claim_issues.append(
                    f"{claim.claim_id}: synthetic evidence is not labelled"
                )
                issues.append(claim_issues[-1])
            claim_grade = evidence_grade(
                GradeInput(
                    evidence_count=len([r for r in refs if r]),
                    coverage=engine.coverage.status,
                    provenance=[r.provenance for r in refs if r],
                    distinct_trips=len({r.trip_id for r in refs if r and r.trip_id}),
                    distinct_signals=len({r.signal for r in refs if r and r.signal}),
                    distinct_sources=len(
                        {r.source_dataset or r.source_database for r in refs if r}
                    ),
                    conflicting=engine.coverage.status == "conflicting",
                )
            )
            if claim.grade != claim_grade:
                claim_issues.append(
                    f"{claim.claim_id}: claim grade does not follow deterministic rules"
                )
                issues.append(claim_issues[-1])
            verified.append(
                claim.model_copy(
                    update={
                        "verifier_status": "rejected" if claim_issues else "verified"
                    }
                )
            )
        grade = evidence_grade(
            GradeInput(
                evidence_count=len(answer.evidence),
                coverage=engine.coverage.status,
                provenance=engine.provenance,
                distinct_trips=len({r.trip_id for r in answer.evidence if r.trip_id}),
                distinct_signals=len({r.signal for r in answer.evidence if r.signal}),
                distinct_sources=len(
                    {r.source_dataset or r.source_database for r in answer.evidence}
                ),
                conflicting=engine.coverage.status == "conflicting",
            )
        )
        final = answer.model_copy(update={"claims": verified, "overall_grade": grade})
        if answer.overall_grade != grade:
            issues.append("overall evidence grade does not follow deterministic rules")
        rendered = render_claims(verified)
        if answer.text != rendered:
            issues.append("answer prose is not exactly rendered from verified claims")
        if issues:
            rejected = [
                c.model_copy(update={"verifier_status": "rejected"})
                for c in answer.claims
            ]
            return final.model_copy(
                update={
                    "claims": rejected,
                    "text": "Answer rejected by TRACE verifier: " + "; ".join(issues),
                    "grounded": False,
                }
            )
        return final.model_copy(update={"grounded": True})
