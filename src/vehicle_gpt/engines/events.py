from __future__ import annotations

import time

from vehicle_gpt.engines.common import base_result, evidence, repository, ts_window
from vehicle_gpt.engines.models import Coverage


class EventEngine:
    name = "events"

    def run(
        self,
        *,
        query_id: str,
        vehicle_id: str | None = None,
        start_ns: int | None = None,
        end_ns: int | None = None,
        event_type: str | None = None,
        include_synthetic: bool = False,
        trip_ids: list[str] | None = None,
        limit: int = 1000,
    ):
        started = time.perf_counter()
        repo = repository()
        rows = repo.events(
            vehicle_id, start_ns, end_ns, event_type, include_synthetic, limit, trip_ids
        )
        refs = [
            evidence(
                "overlay_event",
                r["event_id"],
                r["vehicle_id"],
                r["trip_id"],
                timestamp=r["ts_replay"],
                provenance=r["provenance"],
                calculation="event lookup",
            )
            for r in rows
        ]
        trips = sorted({r["trip_id"] for r in rows})
        cov = Coverage(
            status="adequate" if rows else "insufficient",
            available_rows=len(rows),
            trips=trips,
            limitations=[] if rows else ["No matching operational event records."],
        )
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=vehicle_id,
            trip_ids=trips,
            time_range=ts_window(start_ns, end_ns),
            result={"events": rows, "count": len(rows)},
            method="overlay_event lookup; source order preserved",
            evidence=refs,
            coverage=cov,
            provenance=sorted({r["provenance"] for r in rows}),
            limitations=[
                "Controller state transitions do not establish OEM disengagement reason codes."
            ]
            if any(r["event_type"] == "adas_state_transition" for r in rows)
            else [],
        )
