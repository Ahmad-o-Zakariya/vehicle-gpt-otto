from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vehicle_gpt.repositories.vehicle_repository import VehicleRepository


class CoverageCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    reasons: list[str] = Field(default_factory=list)
    signals_available: dict[str, bool] = Field(default_factory=dict)
    history_seconds: float | None = None
    matching_events: int | None = None
    trips: list[str] = Field(default_factory=list)
    synthetic_signals: list[str] = Field(default_factory=list)


class CoverageChecker:
    def __init__(self, repo: VehicleRepository):
        self.repo = repo

    def check(
        self,
        *,
        vehicle_id: str | None,
        signals: list[str],
        start_ns: int | None = None,
        end_ns: int | None = None,
        min_trips: int = 1,
        event_type: str | None = None,
        min_history_seconds: float | None = None,
        require_denominator: bool = False,
        denominator_signal: str | None = None,
        include_synthetic: bool = False,
        allowed_trip_ids: list[str] | None = None,
    ) -> CoverageCheck:
        reasons = []
        if not vehicle_id:
            return CoverageCheck(
                status="invalid", reasons=["vehicle identity is required"]
            )
        vehicles = {v["vehicle_id"] for v in self.repo.vehicles()}
        if vehicle_id not in vehicles:
            return CoverageCheck(
                status="unavailable", reasons=["unknown vehicle identity"]
            )
        caps = self.repo.capabilities(vehicle_id)
        available = {c["signal"]: c for c in caps}
        flags = {s: s in available for s in signals}
        synthetic_signals = []
        if include_synthetic and allowed_trip_ids:
            with self.repo.connect() as con:
                for signal, ok in list(flags.items()):
                    if ok:
                        continue
                    marks = ",".join("?" for _ in allowed_trip_ids)
                    found = con.execute(
                        """SELECT 1 FROM overlay_sample os JOIN overlay_event oe USING(event_id)
                        WHERE os.signal=? AND os.provenance='synthetic' AND oe.provenance='synthetic'
                          AND oe.trip_id IN ("""
                        + marks
                        + ") LIMIT 1",
                        [signal, *allowed_trip_ids],
                    ).fetchone()
                    if found:
                        flags[signal] = True
                        synthetic_signals.append(signal)
        missing = [s for s, ok in flags.items() if not ok]
        if missing:
            reasons.append("signals unavailable: " + ", ".join(missing))
        if require_denominator and (
            not denominator_signal or denominator_signal not in available
        ):
            reasons.append("required denominator signal is unavailable")
        trips = set()
        trips_by_signal = {}
        history_values = []
        for s in signals:
            c = available.get(s)
            if c:
                history_values.append((c["first_ts_replay_ns"], c["last_ts_replay_ns"]))
        if history_values:
            starts = [x[0] for x in history_values if x[0] is not None]
            ends = [x[1] for x in history_values if x[1] is not None]
            hist = (min(ends) - max(starts)) / 1e9 if starts and ends else None
        else:
            hist = None
        if min_history_seconds is not None and (
            hist is None or hist < min_history_seconds
        ):
            reasons.append(
                f"insufficient common history for requested window ({hist} s observed)"
            )
        with self.repo.connect() as con:
            for signal in signals:
                if signal not in available:
                    continue
                clauses = ["vehicle_id=?", "signal=?", "sample_count>missing_count"]
                params = [vehicle_id, signal]
                if end_ns is not None:
                    clauses.append("first_ts_replay_ns<=?")
                    params.append(end_ns)
                if start_ns is not None:
                    clauses.append("last_ts_replay_ns>=?")
                    params.append(start_ns)
                rows = con.execute(
                    "SELECT trip_id FROM signal_coverage WHERE "
                    + " AND ".join(clauses),
                    params,
                ).fetchall()
                trips_by_signal[signal] = {r[0] for r in rows}
                if signal in synthetic_signals:
                    marks = ",".join("?" for _ in (allowed_trip_ids or []))
                    if marks:
                        synth_rows = con.execute(
                            "SELECT DISTINCT oe.trip_id FROM overlay_sample os JOIN overlay_event oe USING(event_id) WHERE os.signal=? AND os.provenance='synthetic' AND oe.trip_id IN ("
                            + marks
                            + ")",
                            [signal, *(allowed_trip_ids or [])],
                        ).fetchall()
                        trips_by_signal[signal].update(r[0] for r in synth_rows)
                trips.update(trips_by_signal[signal])
                if len(trips_by_signal[signal]) < min_trips:
                    reasons.append(
                        f"insufficient trip coverage for {signal}: need {min_trips}, observed {len(trips_by_signal[signal])}"
                    )
        if (
            start_ns is not None
            and end_ns is not None
            and hist is not None
            and (end_ns - start_ns) / 1e9 > hist
        ):
            reasons.append("requested interval exceeds common signal history")
        matches = None
        if event_type:
            matches = len(
                self.repo.events(vehicle_id, start_ns, end_ns, event_type, limit=10_000)
            )
            if matches == 0:
                reasons.append("required event does not exist in the selected interval")
        if reasons:
            status = (
                "unavailable"
                if missing and len(missing) == len(signals)
                else "insufficient"
            )
        else:
            status = "adequate"
        return CoverageCheck(
            status=status,
            reasons=reasons,
            signals_available=flags,
            history_seconds=hist,
            matching_events=matches,
            trips=sorted(trips),
            synthetic_signals=synthetic_signals,
        )
