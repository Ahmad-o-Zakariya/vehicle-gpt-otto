from __future__ import annotations

from vehicle_gpt.engines.comparisons import ComparisonEngine
from vehicle_gpt.engines.events import EventEngine
from vehicle_gpt.engines.models import Coverage, EngineResult
from vehicle_gpt.engines.precursors import PrecursorEngine
from vehicle_gpt.engines.trends import TrendEngine
from vehicle_gpt.planner.schema import ExecutionPlan
from vehicle_gpt.runtime.splits import is_development_trip


class DeterministicRouter:
    def __init__(self):
        self.events = EventEngine()
        self.trends = TrendEngine()
        self.comparisons = ComparisonEngine()
        self.precursors = PrecursorEngine()

    def execute(self, plan: ExecutionPlan):
        if plan.intent.value == "unsupported" or plan.aggregation == "unsupported":
            return EngineResult(
                engine="unsupported",
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                result={},
                method="deterministic capability resolution",
                coverage=Coverage(
                    status="unavailable",
                    limitations=[
                        plan.unsupported_reason
                        or "The requested operation is unsupported."
                    ],
                ),
                limitations=[
                    plan.unsupported_reason or "The requested operation is unsupported."
                ],
                error_code="unsupported_request",
            )
        time_range = plan.time_range
        start = time_range.start_ns if time_range else None
        end = time_range.end_ns if time_range else None
        if time_range and time_range.wall_clock_claim:
            return EngineResult(
                engine="events",
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                result={"events": [], "count": 0},
                method="wall-clock query withheld: dataset source timezone is unverified",
                coverage=Coverage(
                    status="insufficient",
                    limitations=[
                        "Absolute wall-clock window cannot be aligned safely to the source replay timestamps."
                    ],
                ),
                limitations=[
                    "Dataset does not contain current-day data. Source timezone is unverified; no event is claimed for yesterday."
                ],
                error_code="wall_clock_unsupported",
            )
        if "two_week_history" in plan.required_coverage:
            return EngineResult(
                engine="trends",
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                result={},
                method="coverage gate: required recent history unavailable",
                coverage=Coverage(
                    status="insufficient",
                    limitations=[
                        "The selected vehicle's latest source data is historical and the requested recent two-week interval is unavailable."
                    ],
                ),
                limitations=[
                    plan.unsupported_reason or "Insufficient two-week history."
                ],
                error_code="insufficient_history",
            )
        if plan.engine.value == "events":
            if plan.trip_ids and not plan.include_synthetic:
                raise ValueError(
                    "trip_ids filter is reserved for explicit development-split synthetic queries"
                )
            if plan.include_synthetic and (
                not plan.trip_ids
                or any(not is_development_trip(t) for t in plan.trip_ids)
            ):
                raise ValueError(
                    "synthetic query requires explicit development-split trips; held-out trips are blocked"
                )
            result = self.events.run(
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                start_ns=start,
                end_ns=end,
                event_type=plan.event_type,
                include_synthetic=plan.include_synthetic,
                trip_ids=plan.trip_ids or None,
            )
            return self._attach_limit(result, plan.unsupported_reason)
        if plan.engine.value == "trends":
            if not plan.vehicle_id or not plan.signals:
                raise ValueError("trend plan requires vehicle and signal")
            if plan.aggregation == "largest_drop":
                return EngineResult(
                    engine="trends",
                    query_id=plan.query_id,
                    vehicle_id=plan.vehicle_id,
                    result={},
                    method="requested largest-drop calculation is not implemented",
                    coverage=Coverage(
                        status="unavailable",
                        limitations=[
                            "No validated largest-drop estimator is available for this metric."
                        ],
                    ),
                    limitations=[
                        "The engine did not substitute a first-to-last summary for a largest-drop request."
                    ],
                    error_code="unsupported_operation",
                )
            if len(plan.signals) != 1:
                return EngineResult(
                    engine="trends",
                    query_id=plan.query_id,
                    vehicle_id=plan.vehicle_id,
                    result={},
                    method="multi-signal trend execution is not implemented",
                    coverage=Coverage(
                        status="unavailable",
                        limitations=["This trend engine accepts one signal per plan."],
                    ),
                    limitations=[
                        "No signal was silently selected from a multi-signal request."
                    ],
                    error_code="unsupported_operation",
                )
            result = self.trends.run(
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                signal=plan.signals[0],
                start_ns=start,
                end_ns=end,
                trip_ids=plan.trip_ids or None,
                min_samples=plan.min_samples,
            )
            return self._attach_limit(result, plan.unsupported_reason)
        if plan.engine.value == "comparisons":
            if len(plan.signals) > 1:
                return EngineResult(
                    engine="comparisons",
                    query_id=plan.query_id,
                    vehicle_id=plan.vehicle_id,
                    result={},
                    method="multi-signal comparison is not implemented",
                    coverage=Coverage(
                        status="unavailable",
                        limitations=["Comparison engine accepts one signal per plan."],
                    ),
                    limitations=[
                        "No signal was silently selected from a multi-signal comparison request."
                    ],
                    error_code="unsupported_operation",
                )
            if plan.comparison_vehicles:
                if not plan.signals:
                    raise ValueError("vehicle comparison requires a common signal")
                return self.comparisons.compare_vehicles(
                    query_id=plan.query_id,
                    vehicle_ids=plan.comparison_vehicles,
                    signal=plan.signals[0],
                    min_samples=plan.min_samples,
                )
            if (not plan.vehicle_id or not plan.signals) and (
                plan.aggregation != "energy_throughput" or not plan.vehicle_id
            ):
                raise ValueError("comparison plan requires vehicle and signal")
            result = self.comparisons.run(
                query_id=plan.query_id,
                vehicle_id=plan.vehicle_id,
                signal=plan.signals[0] if plan.signals else "battery.voltage",
                trip_groups=plan.comparison_groups,
                min_samples=plan.min_samples,
                metric="energy_throughput"
                if plan.aggregation == "energy_throughput"
                else "signal_mean",
                operating_labels=(
                    {k: k for k in plan.comparison_groups}
                    if {"city", "highway"} & set(plan.comparison_groups)
                    else None
                ),
            )
            return self._attach_limit(result, plan.unsupported_reason)
        if plan.engine.value == "precursors":
            if plan.event_ids:
                if plan.include_synthetic and not plan.trip_ids:
                    raise ValueError(
                        "synthetic precursor requires explicit development-split trips"
                    )
                result = self.precursors.compare_events(
                    query_id=plan.query_id,
                    event_ids=plan.event_ids,
                    signals=plan.signals or None,
                    include_synthetic=plan.include_synthetic,
                    before_seconds=plan.event_window_before_seconds,
                    after_seconds=plan.event_window_after_seconds,
                )
                if plan.include_synthetic and not set(result.trip_ids) <= set(
                    plan.trip_ids
                ):
                    raise ValueError(
                        "multi-event selection includes trips outside the development split"
                    )
                return self._attach_limit(result, plan.unsupported_reason)
            event_id = plan.filters.get("event_id")
            if not isinstance(event_id, str):
                raise ValueError("precursor plan requires registered event_id filter")
            if plan.include_synthetic and not plan.trip_ids:
                raise ValueError(
                    "synthetic precursor requires an explicit development-split trip"
                )
            result = self.precursors.run(
                query_id=plan.query_id,
                event_id=event_id,
                signals=plan.signals or None,
                include_synthetic=plan.include_synthetic,
                before_seconds=plan.event_window_before_seconds,
                after_seconds=plan.event_window_after_seconds,
            )
            if (
                plan.include_synthetic
                and result.trip_ids
                and not set(result.trip_ids) <= set(plan.trip_ids)
            ):
                raise ValueError(
                    "event trip does not match the explicitly selected synthetic development trip"
                )
            return self._attach_limit(result, plan.unsupported_reason)
        raise ValueError("unregistered engine")

    @staticmethod
    def _attach_limit(result, reason):
        if reason:
            result.limitations.append(reason)
            result.coverage.limitations.append(reason)
            if result.coverage.status == "adequate":
                result.coverage.status = "partial"
        return result
