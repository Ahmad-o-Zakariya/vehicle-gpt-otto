from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from vehicle_gpt.planner.schema import EngineName, ExecutionPlan, Intent, TimeRange
from vehicle_gpt.planner.semantic_schema import (
    SemanticDomain,
    SemanticIntent,
    SemanticOperation,
    SemanticQuery,
    TemporalScope,
)
from vehicle_gpt.repositories.vehicle_repository import VehicleRepository
from vehicle_gpt.runtime.splits import is_development_trip


class ResolutionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


class DeterministicResolver:
    """Resolve semantic slots only through selected vehicle and operational data."""

    def __init__(self, repo: VehicleRepository):
        self.repo = repo

    def _vehicle(
        self, question: str, selected: str | None
    ) -> tuple[str | None, str | None]:
        vehicles = self.repo.vehicles()
        by_id = {v["vehicle_id"]: v for v in vehicles}
        text = _norm(question)
        explicit = []
        for vehicle in vehicles:
            names = {
                _norm(vehicle["vehicle_id"]),
                _norm(" ".join(str(vehicle.get(k) or "") for k in ("make", "model"))),
            }
            names.discard("")
            for name in names:
                if len(name) > 2 and re.search(
                    rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text
                ):
                    explicit.append(vehicle["vehicle_id"])
                    break
        explicit = sorted(set(explicit))
        if len(explicit) > 1:
            return (
                selected,
                "The question names more than one vehicle; choose one vehicle context.",
            )
        mentioned = explicit[0] if explicit else None
        if selected is not None and selected not in by_id:
            return selected, f"Selected vehicle is not registered: {selected}."
        if selected and mentioned and selected != mentioned:
            return (
                selected,
                "The question names a different vehicle than the selected vehicle. Change the selection to continue.",
            )
        vehicle_id = selected or mentioned
        if vehicle_id is None:
            return (
                None,
                "Select a vehicle or name one uniquely so the query can be resolved safely.",
            )
        return vehicle_id, None

    @staticmethod
    def _coverage_dates(capabilities: list[dict]) -> tuple[str | None, str | None]:
        stamps = [
            int(value)
            for row in capabilities
            for value in (row.get("first_ts_replay_ns"), row.get("last_ts_replay_ns"))
            if value is not None
        ]
        if not stamps:
            return None, None
        return tuple(
            datetime.fromtimestamp(stamp / 1e9, UTC).date().isoformat()
            for stamp in (min(stamps), max(stamps))
        )

    def resolve(
        self,
        semantic: SemanticQuery,
        *,
        question: str,
        selected_vehicle_id: str | None,
        query_id: str | None = None,
    ) -> ExecutionPlan:
        qid = query_id or str(uuid4())
        vehicle_id, vehicle_error = self._vehicle(question, selected_vehicle_id)
        if vehicle_error:
            return self._unsupported(qid, vehicle_id, vehicle_error)
        assert vehicle_id is not None
        capabilities = self.repo.capabilities(vehicle_id)
        available = {row["signal"] for row in capabilities}

        expected = {
            SemanticDomain.DRIVING_RANGE: (
                SemanticIntent.TREND,
                SemanticOperation.TREND_SUMMARY,
            ),
            SemanticDomain.FUEL_CONSUMPTION: (
                SemanticIntent.TREND,
                SemanticOperation.LARGEST_DROP,
            ),
            SemanticDomain.ADAS: (
                SemanticIntent.EVENT_LOOKUP,
                SemanticOperation.EVENT_LOOKUP,
            ),
            SemanticDomain.BATTERY_OVERHEATING: (
                SemanticIntent.PRECURSOR,
                SemanticOperation.PRECURSOR_ANALYSIS,
            ),
            SemanticDomain.ENERGY_COMPARISON: (
                SemanticIntent.COMPARISON,
                SemanticOperation.GROUP_COMPARISON,
            ),
        }
        if (
            semantic.domain == SemanticDomain.UNKNOWN
            or semantic.intent == SemanticIntent.UNSUPPORTED
        ):
            return self._unsupported(
                qid,
                vehicle_id,
                "This request is outside the supported VehicleGPT query domains.",
            )
        required = expected.get(semantic.domain)
        if (
            required is None
            or semantic.intent != required[0]
            or semantic.operation != required[1]
        ):
            return self._unsupported(
                qid,
                vehicle_id,
                "The requested operation could not be resolved consistently with its data domain.",
            )

        if semantic.domain == SemanticDomain.DRIVING_RANGE:
            proxy_signals = [
                s
                for s in (
                    "battery.soc",
                    "battery.current",
                    "battery.voltage",
                    "vehicle.speed",
                )
                if s in available
            ]
            if not proxy_signals:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "No registered battery or vehicle measurements support a range-related history review.",
                )
            start_date, end_date = self._coverage_dates(capabilities)
            return ExecutionPlan(
                query_id=qid,
                intent=Intent.TREND,
                engine=EngineName.TRENDS,
                vehicle_id=vehicle_id,
                signals=proxy_signals,
                aggregation="summary",
                required_coverage=["two_week_history"],
                unsupported_reason=(
                    f"No direct range or odometer signal is registered. Available proxy measurements are historical ({start_date} to {end_date}); they cannot establish a current two-week decline."
                ),
            )

        if semantic.domain == SemanticDomain.FUEL_CONSUMPTION:
            required_signals = ["vehicle.fuel_rate", "vehicle.speed"]
            if not set(required_signals) <= available:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "Fuel-rate and speed measurements are not both available for an aligned exploratory proxy.",
                )
            # No direct efficiency signal or validated largest-drop estimator exists.
            return self._unsupported(
                qid,
                vehicle_id,
                "The dataset measures fuel rate (L/h) and speed (m/s), not fuel efficiency. A validated aligned consumption-per-distance largest-drop calculation is not implemented, so no drop time or magnitude is asserted.",
            )

        if semantic.domain == SemanticDomain.ADAS:
            event_types = {
                r["event_type"]
                for r in self.repo.events(
                    vehicle_id=vehicle_id, include_synthetic=False
                )
            }
            event_type = "adas.lateral_control_enable_state_change"
            if event_type not in event_types:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "No real ADAS controller state-transition events are registered for the selected vehicle.",
                )
            scope = semantic.temporal_scope
            time_range = (
                TimeRange(basis="wall_clock", wall_clock_claim=True)
                if scope == TemporalScope.YESTERDAY
                or "yesterday" in question.casefold()
                else None
            )
            return ExecutionPlan(
                query_id=qid,
                intent=Intent.EVENT_LOOKUP,
                engine=EngineName.EVENTS,
                vehicle_id=vehicle_id,
                event_type=event_type,
                time_range=time_range,
                unsupported_reason="Controller state transitions are not OEM-recorded disengagement-reason events.",
            )

        if semantic.domain == SemanticDomain.BATTERY_OVERHEATING:
            if "battery.temperature" not in available:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "Battery-temperature evidence is unavailable for the selected vehicle.",
                )
            candidates = self.repo.events(
                vehicle_id=vehicle_id,
                event_type="diagnostic.warning",
                include_synthetic=True,
                limit=10000,
            )
            matches = []
            for event in candidates:
                try:
                    metadata = json.loads(event.get("event_metadata_json") or "{}")
                except TypeError, json.JSONDecodeError:
                    continue
                if (
                    metadata.get("code") == "BATT_OVERTEMP"
                    and event["provenance"] == "synthetic"
                    and is_development_trip(event["trip_id"])
                ):
                    matches.append(event)
            if not matches:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "No development-split battery-overtemperature warning events are available for the selected vehicle.",
                )
            overlay_signals = self.repo.overlay_signals_for_injections(
                sorted({e["injection_id"] for e in matches if e.get("injection_id")})
            )
            thermal = [
                s
                for s in (
                    "battery.temperature",
                    "thermal.coolant_temperature_inlet",
                    "thermal.coolant_pump_duty",
                )
                if s in available or s in overlay_signals
            ]
            if not thermal:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "No registered thermal signals are available for the selected vehicle.",
                )
            text = question.casefold()
            seconds_match = re.search(r"\b(\d+)\s*(?:seconds?|secs?)\b", text)
            before = int(seconds_match.group(1)) if seconds_match else 60
            if before < 1 or before > 60:
                return self._unsupported(
                    qid,
                    vehicle_id,
                    "The precursor engine supports pre-warning windows from 1 to 60 seconds; the requested duration is outside that range.",
                )
            # "Before" queries are strict: offset zero is an anchor, never a trajectory point.
            after = (
                0
                if "before" in text
                or semantic.temporal_scope == TemporalScope.BEFORE_EVENT
                else 60
            )
            return ExecutionPlan(
                query_id=qid,
                intent=Intent.PRECURSOR,
                engine=EngineName.PRECURSORS,
                vehicle_id=vehicle_id,
                event_type="diagnostic.warning",
                event_ids=[e["event_id"] for e in matches],
                trip_ids=[e["trip_id"] for e in matches],
                signals=thermal,
                include_synthetic=True,
                event_window_before_seconds=min(before, 60),
                event_window_after_seconds=min(after, 60),
                unsupported_reason="Development-split synthetic warning scenario only; measurements are synthetic pipeline-testing evidence and temporal precedence does not establish causation.",
            )

        if semantic.domain == SemanticDomain.ENERGY_COMPARISON:
            return self._unsupported(
                qid,
                vehicle_id,
                "The operational dataset has no verified city/highway labels or matched segments; speed alone cannot define those groups.",
            )
        return self._unsupported(qid, vehicle_id, "Unsupported query.")

    @staticmethod
    def _unsupported(
        query_id: str, vehicle_id: str | None, reason: str
    ) -> ExecutionPlan:
        return ExecutionPlan(
            query_id=query_id,
            intent=Intent.UNSUPPORTED,
            engine=EngineName.UNSUPPORTED,
            vehicle_id=vehicle_id,
            aggregation="unsupported",
            unsupported_reason=reason,
        )
