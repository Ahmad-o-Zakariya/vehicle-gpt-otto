from __future__ import annotations

import statistics
import time
from itertools import pairwise

from vehicle_gpt.engines.common import base_result, evidence, repository
from vehicle_gpt.engines.models import Coverage, EvidenceReference


class ComparisonEngine:
    name = "comparisons"

    def run(
        self,
        *,
        query_id: str,
        vehicle_id: str,
        signal: str,
        trip_groups: dict[str, list[str]],
        min_samples: int = 10,
        operating_labels: dict[str, str] | None = None,
        metric: str = "signal_mean",
    ):
        started = time.perf_counter()
        if operating_labels and set(operating_labels.values()) <= {"city", "highway"}:
            if not {"city", "highway"} <= set(operating_labels.values()):
                return base_result(
                    started,
                    engine=self.name,
                    query_id=query_id,
                    vehicle_id=vehicle_id,
                    result={},
                    method="verified labelled group comparison",
                    coverage=Coverage(
                        status="insufficient",
                        limitations=["Both city and highway labels are required."],
                    ),
                    limitations=["No valid city/highway pair."],
                )
            # The dataset does not contain validated driving-condition labels.
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                vehicle_id=vehicle_id,
                result={},
                method="verified labelled group comparison",
                coverage=Coverage(
                    status="unavailable",
                    limitations=[
                        "No validated city/highway labels exist in this dataset."
                    ],
                ),
                limitations=[
                    "Unsupported comparison: route classes are not present; no city/highway inference is performed."
                ],
                error_code="unsupported_comparison",
            )
        repo = repository()
        groups = {}
        refs = []
        trips = []
        limitations = []
        cap = next(
            (c for c in repo.capabilities(vehicle_id) if c["signal"] == signal), None
        )
        signal_unit = cap["unit"] if cap else "unit of signal"
        for label, ids in trip_groups.items():
            vals = []
            for trip_id in ids:
                if metric == "energy_throughput":
                    energy, audit_rows, note = self._trip_energy(
                        repo, vehicle_id, trip_id
                    )
                    if note:
                        limitations.append(f"{trip_id}: {note}")
                    if energy is not None:
                        vals.append(energy)
                        trips.append(trip_id)
                    refs.extend(
                        evidence(
                            "canonical_measurement",
                            r["measurement_id"],
                            vehicle_id,
                            trip_id,
                            r["signal"],
                            r["ts_replay"],
                            r["unit"],
                            r["provenance"],
                            f"group:{label}",
                            r["source_dataset"],
                        )
                        for r in audit_rows
                    )
                    continue
                try:
                    rows = repo.samples(vehicle_id, signal, trip_ids=[trip_id])
                except LookupError as exc:
                    limitations.append(str(exc))
                    continue
                good = [
                    r
                    for r in rows
                    if r["value"] is not None and r["quality_flag"] == "ok"
                ]
                vals.extend(float(r["value"]) for r in good)
                trips.append(trip_id)
                refs.extend(
                    evidence(
                        "canonical_measurement",
                        r["measurement_id"],
                        vehicle_id,
                        trip_id,
                        signal,
                        r["ts_replay"],
                        r["unit"],
                        r["provenance"],
                        f"group:{label}",
                        r["source_dataset"],
                    )
                    for r in good[:100]
                )
            groups[label] = {
                "trips": ids,
                "sample_count": len(vals),
                "mean": statistics.fmean(vals) if vals else None,
                "unit": "kWh/trip (gross absolute battery energy throughput)"
                if metric == "energy_throughput"
                else signal_unit,
            }
            if len(vals) < min_samples:
                limitations.append(
                    f"Group {label!r} has {len(vals)} valid samples; minimum is {min_samples}."
                )
        for label, group in groups.items():
            if group["mean"] is not None:
                refs.append(
                    EvidenceReference(
                        evidence_id=f"{query_id}-calc-{label}",
                        source_database="operational",
                        source_table="calculation",
                        record_id=f"{query_id}:result.groups.{label}.mean",
                        source_dataset=cap["source_dataset"] if cap else None,
                        vehicle_id=vehicle_id,
                        signal=signal,
                        unit=group["unit"],
                        provenance="real",
                        calculation=f"result.groups.{label}.mean",
                        record_count=group["sample_count"],
                        transformation="arithmetic mean within named trip group",
                    )
                )
        means = [g["mean"] for g in groups.values() if g["mean"] is not None]
        delta = abs(means[-1] - means[0]) if len(means) >= 2 else None
        status = (
            "adequate"
            if len(groups) >= 2
            and all(g["sample_count"] >= min_samples for g in groups.values())
            else "insufficient"
        )
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=vehicle_id,
            trip_ids=sorted(set(trips)),
            result={"groups": groups, "absolute_difference": delta},
            units={
                "group_mean": "kWh/trip (gross absolute battery energy throughput)"
                if metric == "energy_throughput"
                else signal_unit,
                "absolute_difference": "kWh/trip (gross absolute battery energy throughput)"
                if metric == "energy_throughput"
                else "unit of signal",
            },
            method=(
                "Per-trip integral of absolute V×A using trapezoids between paired measured timestamps; intervals >2.5× median are excluded. This is gross throughput, not signed consumption."
                if metric == "energy_throughput"
                else "per-group arithmetic mean of valid canonical samples; no unit conversion or interpolation"
            ),
            evidence=refs,
            coverage=Coverage(
                status=status,
                available_rows=sum(g["sample_count"] for g in groups.values()),
                trips=sorted(set(trips)),
                limitations=limitations,
            ),
            provenance=["real"],
            limitations=limitations,
        )

    @staticmethod
    def _trip_energy(repo, vehicle_id, trip_id):
        try:
            voltage = repo.samples(vehicle_id, "battery.voltage", trip_ids=[trip_id])
            current = repo.samples(vehicle_id, "battery.current", trip_ids=[trip_id])
        except LookupError as exc:
            return None, [], str(exc)
        v = {
            r["ts_replay_ns"]: r
            for r in voltage
            if r["value"] is not None
            and r["quality_flag"] == "ok"
            and r["ts_replay_ns"] is not None
        }
        i = {
            r["ts_replay_ns"]: r
            for r in current
            if r["value"] is not None
            and r["quality_flag"] == "ok"
            and r["ts_replay_ns"] is not None
        }
        stamps = sorted(v.keys() & i.keys())
        if len(stamps) < 2:
            return None, [], "fewer than two paired valid voltage/current samples"
        gaps = [(b - a) / 1e9 for a, b in pairwise(stamps) if b > a]
        if not gaps:
            return None, [], "no positive timestamp intervals"
        import statistics as stats

        median_gap = stats.median(gaps)
        max_gap = 2.5 * median_gap
        energy = 0.0
        used = 0
        skipped = 0.0
        power = [abs(float(v[t]["value"]) * float(i[t]["value"])) for t in stamps]
        for idx, (a, b) in enumerate(pairwise(stamps)):
            dt = (b - a) / 1e9
            if dt <= 0 or dt > max_gap:
                skipped += max(dt, 0.0)
                continue
            energy += (power[idx] + power[idx + 1]) * 0.5 * dt / 3_600_000.0
            used += 1
        if used == 0:
            return None, [], "all paired sample intervals were irregular"
        audit = [v[stamps[0]], i[stamps[0]], v[stamps[-1]], i[stamps[-1]]]
        note = (
            f"{skipped:.3f} seconds across irregular gaps excluded" if skipped else None
        )
        return energy, audit, note

    def compare_vehicles(
        self,
        *,
        query_id: str,
        vehicle_ids: list[str],
        signal: str,
        min_samples: int = 10,
    ):
        started = time.perf_counter()
        repo = repository()
        groups = {}
        refs = []
        trips = []
        units = set()
        limitations = []
        if len(vehicle_ids) < 2:
            return base_result(
                started,
                engine=self.name,
                query_id=query_id,
                result={},
                method="same-signal vehicle comparison",
                coverage=Coverage(
                    status="invalid",
                    limitations=["At least two vehicles are required."],
                ),
                limitations=["Vehicle comparison requires two vehicles."],
                error_code="invalid_comparison",
            )
        for vehicle in vehicle_ids:
            caps = repo.capabilities(vehicle)
            cap = next((x for x in caps if x["signal"] == signal), None)
            if cap is None:
                limitations.append(f"{vehicle}: signal {signal} unavailable")
                continue
            units.add(cap["unit"])
            try:
                rows = repo.samples(vehicle, signal, limit=100_000)
            except LookupError as exc:
                limitations.append(str(exc))
                continue
            good = [
                r for r in rows if r["value"] is not None and r["quality_flag"] == "ok"
            ]
            groups[vehicle] = {
                "sample_count": len(good),
                "trip_count": len({r["trip_id"] for r in good}),
                "mean": statistics.fmean(float(r["value"]) for r in good)
                if good
                else None,
                "unit": cap["unit"],
            }
            trips.extend(r["trip_id"] for r in good)
            refs.extend(
                evidence(
                    "canonical_measurement",
                    r["measurement_id"],
                    vehicle,
                    r["trip_id"],
                    signal,
                    r["ts_replay"],
                    r["unit"],
                    r["provenance"],
                    "vehicle mean",
                )
                for r in good[:20]
            )
            if len(good) < min_samples:
                limitations.append(
                    f"{vehicle}: {len(good)} samples; minimum is {min_samples}"
                )
            refs.append(
                EvidenceReference(
                    evidence_id=f"{query_id}-calc-{vehicle}",
                    source_database="operational",
                    source_table="calculation",
                    record_id=f"{query_id}:result.groups.{vehicle}.mean",
                    source_dataset=cap["source_dataset"],
                    vehicle_id=vehicle,
                    signal=signal,
                    unit=cap["unit"],
                    provenance="real",
                    calculation=f"result.groups.{vehicle}.mean",
                    record_count=len(good),
                    transformation="arithmetic mean over valid canonical samples",
                )
            )
        if len(units) > 1:
            limitations.append("Signal units differ between vehicles.")
        supported = (
            len(groups) == len(vehicle_ids)
            and len(units) == 1
            and all(g["sample_count"] >= min_samples for g in groups.values())
        )
        if len(groups) > 1:
            limitations.append(
                "Vehicle-specific hardware, routes, and operating conditions may differ; the comparison is descriptive only."
            )
        return base_result(
            started,
            engine=self.name,
            query_id=query_id,
            vehicle_id=None,
            trip_ids=sorted(set(trips)),
            result={"groups": groups},
            units={"mean": next(iter(units), "unit of signal")},
            method="same canonical signal and units; mean of valid measured samples; no interpolation",
            evidence=refs,
            coverage=Coverage(
                status="adequate" if supported else "insufficient",
                available_rows=sum(g["sample_count"] for g in groups.values()),
                trips=sorted(set(trips)),
                limitations=limitations,
            ),
            provenance=["real"],
            limitations=limitations,
        )
