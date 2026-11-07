from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
SIGNALS = frozenset(
    yaml.safe_load((ROOT / "configs/signals.yaml").read_text())["signals"]
)
EVENT_TYPES = frozenset(
    {
        "adas.lateral_control_enable_state_change",
        "adas.synthetic_disengagement",
        "diagnostic.dtc",
        "diagnostic.freeze_frame",
        "diagnostic.qnx_log_line",
        "diagnostic.warning",
        "scenario.unrelated_distractor_change",
        "thermal.battery_temperature_ramp",
        "thermal.coolant_inlet_sensor_dropout",
        "thermal.coolant_pump_duty_drop",
    }
)


class Intent(StrEnum):
    EVENT_LOOKUP = "event_lookup"
    TREND = "trend"
    COMPARISON = "comparison"
    PRECURSOR = "precursor"
    UNSUPPORTED = "unsupported"


class EngineName(StrEnum):
    EVENTS = "events"
    TRENDS = "trends"
    COMPARISONS = "comparisons"
    PRECURSORS = "precursors"
    UNSUPPORTED = "unsupported"


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_ns: int | None = Field(default=None, ge=0, le=4_102_444_800_000_000_000)
    end_ns: int | None = Field(default=None, ge=0, le=4_102_444_800_000_000_000)
    timezone: str | None = None
    basis: str = "source_replay"
    wall_clock_claim: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.start_ns is not None
            and self.end_ns is not None
            and self.end_ns < self.start_ns
        ):
            raise ValueError("time range end precedes start")
        return self


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query_id: str = Field(min_length=1, max_length=128)
    intent: Intent
    vehicle_id: str | None = None
    time_range: TimeRange | None = None
    signals: list[str] = Field(default_factory=list, max_length=16)
    event_type: str | None = None
    event_ids: list[str] = Field(default_factory=list, max_length=20)
    trip_ids: list[str] = Field(default_factory=list, max_length=100)
    include_synthetic: bool = False
    engine: EngineName
    aggregation: str | None = None
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    comparison_groups: dict[str, list[str]] = Field(default_factory=dict)
    comparison_vehicles: list[str] = Field(default_factory=list, max_length=20)
    event_window_before_seconds: int = Field(default=60, ge=0, le=60)
    event_window_after_seconds: int = Field(default=60, ge=0, le=60)
    required_coverage: list[str] = Field(default_factory=list)
    min_samples: int = Field(default=3, ge=1, le=100_000)
    output_format: str = Field(default="trace_claims", pattern="^trace_claims$")
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def registered_tools_only(self):
        expected = {
            Intent.EVENT_LOOKUP: EngineName.EVENTS,
            Intent.TREND: EngineName.TRENDS,
            Intent.COMPARISON: EngineName.COMPARISONS,
            Intent.PRECURSOR: EngineName.PRECURSORS,
            Intent.UNSUPPORTED: EngineName.UNSUPPORTED,
        }
        if self.engine != expected[self.intent]:
            raise ValueError("intent and engine do not match")
        unknown = set(self.signals) - SIGNALS
        if unknown:
            raise ValueError("unregistered signals: " + ", ".join(sorted(unknown)))
        if self.event_type is not None and self.event_type not in EVENT_TYPES:
            raise ValueError("unregistered event type")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise ValueError("duplicate event IDs are not allowed")
        if self.intent != Intent.COMPARISON and self.comparison_groups:
            raise ValueError("comparison_groups only apply to comparison intent")
        if self.intent != Intent.COMPARISON and self.comparison_vehicles:
            raise ValueError("comparison_vehicles only apply to comparison intent")
        if self.aggregation not in {
            None,
            "mean",
            "median",
            "minimum",
            "maximum",
            "energy_throughput",
            "summary",
            "trip_comparison",
            "largest_drop",
            "unsupported",
        }:
            raise ValueError("unregistered aggregation")
        if self.signals and len(set(self.signals)) != len(self.signals):
            raise ValueError("duplicate signal names are not allowed")
        if any(
            not re.fullmatch(r"[A-Za-z0-9_:-]{1,64}", label)
            for label in self.comparison_groups
        ):
            raise ValueError("comparison group names must be short registered labels")
        if len(set(self.trip_ids)) != len(self.trip_ids) or len(
            set(self.comparison_vehicles)
        ) != len(self.comparison_vehicles):
            raise ValueError("duplicate trip or vehicle IDs are not allowed")
        if set(self.filters) - {"event_id"}:
            raise ValueError("unregistered plan filter")
        return self
