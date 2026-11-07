from __future__ import annotations

import re
from datetime import datetime

from vehicle_gpt.runtime.messages import LogEvent, Protocol, Provenance, QualityFlag

LINE = re.compile(
    r"^(?P<time>.+?)\s{2,}(?P<set>\S+)\s{2,}(?P<buffer>\S+)\s{2,}(?P<code>\S+)\s{2,}(?P<message>.*)$"
)


def parse_slog2info_line(
    line: str,
    *,
    vehicle_id: str = "unknown",
    trip_id: str | None = None,
    provenance: Provenance = Provenance.UNKNOWN,
    timezone: str | None = None,
    year: int | None = None,
) -> LogEvent:
    """Parse the documented default five-column slog2info text layout."""
    raw = line.rstrip("\r\n")
    match = LINE.match(raw)
    if not match:
        raise ValueError("malformed slog2info line; expected five documented columns")
    values = match.groupdict()
    timestamp = values["time"]
    try:
        parsed = datetime.strptime(f"2000 {timestamp}", "%Y %b %d %H:%M:%S.%f")
    except ValueError as exc:
        raise ValueError(
            "unsupported slog2info timestamp; expected 'Mon DD HH:MM:SS.mmm'"
        ) from exc
    parts = {
        "month": parsed.month,
        "day": parsed.day,
        "hour": parsed.hour,
        "minute": parsed.minute,
        "second": parsed.second,
        "microsecond": parsed.microsecond,
    }
    if year is not None:
        parsed = parsed.replace(year=year)
        timestamp = parsed.isoformat(timespec="microseconds")
    if timezone:
        timestamp = f"{timestamp} [{timezone}]"
    set_name = values["set"]
    component = set_name.rsplit(".", 1)[0] if "." in set_name else set_name
    return LogEvent(
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        protocol=Protocol.QNX_LOG,
        source_timestamp=timestamp,
        provenance=provenance,
        quality_flag=QualityFlag.OK,
        buffer_set=set_name,
        buffer_name=values["buffer"].rstrip("*"),
        event_code=values["code"],
        message=values["message"],
        severity=None,
        component=component,
        unknown_fields=["buffer_oldest_marker"]
        if values["buffer"].endswith("*")
        else [],
        timestamp_components=parts,
        timestamp_year=year,
    )
