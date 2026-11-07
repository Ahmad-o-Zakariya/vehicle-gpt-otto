from __future__ import annotations

import statistics
import time
from itertools import pairwise

from vehicle_gpt.engines.common import base_result, evidence, repository, ts_window
from vehicle_gpt.engines.models import Coverage


class TrendEngine:
    name = "trends"

    def run(
        self,
        *,
        query_id: str,
        vehicle_id: str,
        signal: str,
        start_ns: int | None = None,
        end_ns: int | None = None,
        trip_ids: list[str] | None = None,
        min_samples: int = 3,
    ):
        started = time.perf_counter()
        repo = repository()
        try:
            rows = repo.samples(vehicle_id, signal, start_ns, end_ns, trip_ids)
        except LookupError as exc:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                vehicle_id=vehicle_id,
                result={},
                method="canonical_measurement summary statistics",
                coverage=Coverage(status="unavailable", limitations=[str(exc)]),
                limitations=[str(exc)],
                error_code="signal_unavailable",
            )
        valid = [
            r
            for r in rows
            if r["value"] is not None
            and r["quality_flag"] == "ok"
            and r["ts_replay_ns"] is not None
        ]
        vals = [float(r["value"]) for r in valid]
        trip_list = sorted({r["trip_id"] for r in valid})
        if len(vals) < min_samples:
            status = "insufficient"
            limitations = [
                f"Need at least {min_samples} valid samples; found {len(vals)}."
            ]
        else:
            status = "adequate"
            limitations = []
        gaps = [
            (b["ts_replay_ns"] - a["ts_replay_ns"]) / 1e9 for a, b in pairwise(valid)
        ]
        med = statistics.median(gaps) if gaps else None
        irregular = bool(med and any(abs(g - med) > 0.2 * med for g in gaps))
        start = vals[0] if vals else None
        end = vals[-1] if vals else None
        duration = (
            (valid[-1]["ts_replay_ns"] - valid[0]["ts_replay_ns"]) / 1e9
            if len(valid) > 1
            else 0
        )
        result = {
            "count": len(vals),
            "mean": statistics.fmean(vals) if vals else None,
            "median": statistics.median(vals) if vals else None,
            "minimum": min(vals) if vals else None,
            "maximum": max(vals) if vals else None,
            "first_value": start,
            "last_value": end,
            "absolute_change": end - start if vals else None,
            "relative_change_percent": (
                (end - start) / abs(start) * 100 if start else None
            )
            if vals
            else None,
            "rate_per_hour": ((end - start) / (duration / 3600) if duration else None)
            if vals
            else None,
            "duration_seconds": duration,
            "sampling_irregular": irregular,
            "sampling_gaps_median_seconds": med,
            "first_timestamp": valid[0]["ts_replay"] if valid else None,
            "last_timestamp": valid[-1]["ts_replay"] if valid else None,
            "points": [
                {
                    "ts": r["ts_replay"],
                    "value": r["value"],
                    "trip_id": r["trip_id"],
                    "quality_flag": r["quality_flag"],
                    "provenance": r["provenance"],
                }
                for r in valid[:: max(1, len(valid) // 2000)][:2000]
            ],
            "source_sample_count": len(valid),
        }
        refs = [
            evidence(
                "canonical_measurement",
                r["measurement_id"],
                vehicle_id,
                r["trip_id"],
                signal,
                r["ts_replay"],
                r["unit"],
                r["provenance"],
                "sample audit reference",
                r["source_dataset"],
            )
            for r in valid[:5] + valid[-5:]
        ]
        missing = len(rows) - len(valid)
        if missing:
            limitations.append(
                f"{missing} rows are missing, flagged, or lack replay timestamps; they were excluded without interpolation."
            )
        if irregular:
            limitations.append(
                "Sampling intervals are irregular; rate-of-change summaries may be misleading."
            )
        coverage = Coverage(
            status=status,
            available_rows=len(valid),
            missing_rows=missing,
            trips=trip_list,
            sampling_median_seconds=med,
            limitations=limitations,
        )
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=vehicle_id,
            trip_ids=trip_list,
            time_range=ts_window(start_ns, end_ns),
            result=result,
            units={
                "mean": "unit of signal",
                "absolute_change": "unit of signal",
                "rate_per_hour": "unit/hour",
            },
            method="valid real canonical samples; no interpolation; ordered by replay timestamp",
            evidence=refs,
            coverage=coverage,
            missing_data=["source missing/flagged rows excluded from numeric summaries"]
            if missing
            else [],
            provenance=sorted({r["provenance"] for r in valid}),
            limitations=limitations,
        )
