from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SemanticIntent(StrEnum):
    EVENT_LOOKUP = "event_lookup"
    TREND = "trend"
    COMPARISON = "comparison"
    PRECURSOR = "precursor"
    UNSUPPORTED = "unsupported"


class SemanticDomain(StrEnum):
    DRIVING_RANGE = "driving_range"
    FUEL_CONSUMPTION = "fuel_consumption"
    ADAS = "adas"
    BATTERY_OVERHEATING = "battery_overheating"
    ENERGY_COMPARISON = "energy_comparison"
    UNKNOWN = "unknown"


class SemanticOperation(StrEnum):
    TREND_SUMMARY = "trend_summary"
    LARGEST_DROP = "largest_drop"
    EVENT_LOOKUP = "event_lookup"
    PRECURSOR_ANALYSIS = "precursor_analysis"
    GROUP_COMPARISON = "group_comparison"
    UNSUPPORTED = "unsupported"


class TemporalScope(StrEnum):
    LAST_TWO_WEEKS = "last_two_weeks"
    YESTERDAY = "yesterday"
    BEFORE_EVENT = "before_event"
    EXPLICIT_DURATION = "explicit_duration"
    UNSPECIFIED = "unspecified"


class SemanticQuery(BaseModel):
    """Small model output: language semantics only, never repository identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    intent: SemanticIntent
    domain: SemanticDomain
    operation: SemanticOperation
    temporal_scope: TemporalScope
