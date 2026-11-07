from __future__ import annotations

import time

from vehicle_gpt.engines.common import base_result, evidence, repository
from vehicle_gpt.engines.models import Coverage


class PrecursorEngine:
    name = "precursors"

    def run(
        self,
        *,
        query_id: str,
        event_id: str,
        signals: list[str] | None = None,
        include_synthetic: bool = False,
        before_seconds: int = 60,
        after_seconds: int = 60,
    ):
        started = time.perf_counter()
        repo = repository()
        with repo.connect() as con:
            ev = con.execute(
                "SELECT * FROM overlay_event WHERE event_id=?", (event_id,)
            ).fetchone()
        if ev is None:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                result={},
                method="event-centred ±60 second window",
                coverage=Coverage(
                    status="unavailable",
                    limitations=["Requested event does not exist in operational data."],
                ),
                limitations=["Unknown event ID."],
                error_code="event_unavailable",
            )
        ev = dict(ev)
        if ev["provenance"] == "synthetic" and not include_synthetic:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                vehicle_id=ev["vehicle_id"],
                trip_ids=[ev["trip_id"]],
                result={},
                method="synthetic event hidden by default",
                coverage=Coverage(
                    status="unavailable",
                    limitations=["Synthetic overlay was not explicitly requested."],
                ),
                limitations=[
                    "Synthetic evidence is excluded unless a development-split query explicitly opts in."
                ],
                error_code="synthetic_data_not_enabled",
            )
        if ev["provenance"] == "synthetic" and include_synthetic:
            from vehicle_gpt.runtime.splits import is_development_trip

            if not is_development_trip(ev["trip_id"]):
                return base_result(
                    started,
                    engine=self.name,
                    query_id=query_id,
                    vehicle_id=ev["vehicle_id"],
                    trip_ids=[ev["trip_id"]],
                    result={},
                    method="held-out synthetic event blocked from operational inference",
                    coverage=Coverage(
                        status="unavailable",
                        limitations=[
                            "Held-out synthetic patterns are reserved for evaluation only."
                        ],
                    ),
                    limitations=[
                        "Held-out synthetic pattern is not available to query-time analysis."
                    ],
                    error_code="held_out_data_blocked",
                )
        rows = repo.event_window(event_id)
        if after_seconds == 0:
            # The warning is exposed as a separate anchor, never as a pre-warning sample.
            rows = [r for r in rows if -before_seconds <= r["offset_seconds"] < 0]
        else:
            rows = [
                r
                for r in rows
                if -before_seconds <= r["offset_seconds"] <= after_seconds
            ]
        if signals:
            rows = [r for r in rows if r["signal"] in signals]
        ref = evidence(
            "overlay_event",
            event_id,
            ev["vehicle_id"],
            ev["trip_id"],
            timestamp=ev["ts_replay"],
            provenance=ev["provenance"],
            calculation="event anchor",
        )
        signal_refs = []
        for r in rows:
            if r.get("recovered_from_overlay"):
                for overlay_id in r.get("overlay_sample_ids", []):
                    signal_refs.append(
                        evidence(
                            "overlay_sample",
                            overlay_id,
                            r["vehicle_id"],
                            r["trip_id"],
                            r["signal"],
                            unit=r["unit"],
                            provenance="synthetic",
                            calculation="read-time recovery of contaminated frozen event-window bucket",
                        )
                    )
            elif r["source_measurement_id"] is not None:
                signal_refs.append(
                    evidence(
                        "canonical_measurement",
                        r["source_measurement_id"],
                        r["vehicle_id"],
                        r["trip_id"],
                        r["signal"],
                        r["ts_replay"],
                        r["unit"],
                        r["provenance"],
                        "stored event-window sample",
                        r["source_dataset"],
                    )
                )
            else:
                rid = f"{event_id}|{r['offset_seconds']}|{r['signal']}"
                signal_refs.append(
                    evidence(
                        "event_window",
                        rid,
                        ev["vehicle_id"],
                        ev["trip_id"],
                        r["signal"],
                        ev["ts_replay"],
                        r["unit"],
                        r["provenance"],
                        "stored synthetic event-window sample",
                    )
                )
        timeline = [
            {
                "offset_seconds": r["offset_seconds"],
                "signal": r["signal"],
                "value": r["value"],
                "unit": r["unit"],
                "quality_flag": r["quality_flag"],
                "provenance": r["provenance"],
                "source_measurement_id": r["source_measurement_id"],
                "recovered_from_overlay": bool(r.get("recovered_from_overlay", False)),
                "interpretation": (
                    "synthetic overlay recovered from source records"
                    if r.get("recovered_from_overlay")
                    else "contaminated frozen value excluded"
                    if r["quality_flag"] == "contaminated_unrecoverable"
                    else "source or derived event-window sample"
                ),
            }
            for r in rows
        ]
        prov = sorted({ev["provenance"], *(r["provenance"] for r in rows)})
        limitations = ["Temporal precedence is not evidence of causation."]
        if not rows:
            limitations.append(
                "No stored event-window samples matched the selected signals."
            )
        if "synthetic" in prov:
            limitations.append(
                "Synthetic overlay measurements are explicitly marked and are not source observations."
            )
        if any(r.get("recovered_from_overlay") for r in rows):
            limitations.append(
                "Known mixed real+overlay buckets from frozen v0.1.0 were corrected at read time using their synthetic overlay records; the database was not modified."
            )
        if any(r["quality_flag"] == "contaminated_unrecoverable" for r in rows):
            limitations.append(
                "An unrecoverable mixed-provenance bucket was retained as missing and excluded from numeric interpretation."
            )
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=ev["vehicle_id"],
            trip_ids=[ev["trip_id"]],
            result={
                "event": ev,
                "event_anchor": {
                    "offset_seconds": 0,
                    "timestamp": ev["ts_replay"],
                    "role": "warning marker; not included in preceding samples",
                },
                "timeline": timeline,
                "timeline_count": len(timeline),
                "interpretation": "temporally associated only",
            },
            method="stored event_window rows around event; no causal inference",
            evidence=[ref, *signal_refs],
            coverage=Coverage(
                status="adequate" if rows else "insufficient",
                available_rows=len(rows),
                trips=[ev["trip_id"]],
                limitations=limitations,
            ),
            provenance=prov,
            limitations=limitations,
        )

    def compare_events(
        self,
        *,
        query_id: str,
        event_ids: list[str],
        signals: list[str] | None = None,
        include_synthetic: bool = False,
        before_seconds: int = 60,
        after_seconds: int = 60,
    ):
        started = time.perf_counter()
        if len(event_ids) < 2:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                result={},
                method="repeated event-centred patterns",
                coverage=Coverage(
                    status="invalid",
                    limitations=[
                        "At least two events are required for recurrence analysis."
                    ],
                ),
                limitations=["Insufficient event count for recurrence analysis."],
                error_code="insufficient_events",
            )
        results = [
            self.run(
                query_id=f"{query_id}-{idx}",
                event_id=event_id,
                signals=signals,
                include_synthetic=include_synthetic,
                before_seconds=before_seconds,
                after_seconds=after_seconds,
            )
            for idx, event_id in enumerate(event_ids)
        ]
        blocked = [r for r in results if r.error_code]
        if blocked:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                result={"events": []},
                method="multi-event comparison blocked by event access policy",
                coverage=Coverage(
                    status="unavailable",
                    limitations=[b.limitations[0] for b in blocked],
                ),
                limitations=[b.limitations[0] for b in blocked],
                error_code=blocked[0].error_code,
            )
        per_event = []
        for result in results:
            entries = result.result.get("timeline", [])
            pre = {
                r["signal"]
                for r in entries
                if r["offset_seconds"] < 0
                and r["value"] is not None
                and r["quality_flag"] == "ok"
            }
            per_event.append(
                {
                    "event_id": result.result["event"]["event_id"],
                    "event_type": result.result["event"]["event_type"],
                    "event_timestamp": result.result["event"].get("ts_replay"),
                    "event_anchor_offset_seconds": 0,
                    "trip_id": result.trip_ids[0],
                    "pre_event_signals": sorted(pre),
                    "sample_count": len(entries),
                    "synthetic": result.result["event"]["provenance"] == "synthetic",
                    "timeline": entries,
                }
            )
        repeated = set(per_event[0]["pre_event_signals"])
        for item in per_event[1:]:
            repeated.intersection_update(item["pre_event_signals"])
        refs = [ref for result in results for ref in result.evidence]
        limitations = [
            "Repeated temporal patterns are associations, not causal evidence."
        ]
        if any(x["synthetic"] for x in per_event):
            limitations.append("One or more events or samples are synthetic overlays.")
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=results[0].vehicle_id,
            trip_ids=sorted({t for r in results for t in r.trip_ids}),
            result={
                "events": per_event,
                "event_count": len(per_event),
                "repeated_pre_event_signals": sorted(repeated),
            },
            method="intersection of measured, quality-ok signals at negative offsets in stored event windows",
            evidence=refs,
            coverage=Coverage(
                status="partial"
                if any(x["synthetic"] for x in per_event)
                else "adequate",
                available_rows=sum(x["sample_count"] for x in per_event),
                trips=sorted({t for r in results for t in r.trip_ids}),
                limitations=limitations,
            ),
            provenance=sorted({p for r in results for p in r.provenance}),
            limitations=limitations,
        )
