from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Protocol(StrEnum):
    CAN = "can"
    SOMEIP = "someip"
    VHAL = "vhal"
    QNX_LOG = "qnx_log"
    INTERNAL = "internal"


class Provenance(StrEnum):
    REAL = "real"
    SYNTHETIC = "synthetic"
    REPLAYED = "replayed"
    UNKNOWN = "unknown"


class QualityFlag(StrEnum):
    OK = "ok"
    SOURCE_MISSING = "source_missing"
    OUT_OF_RANGE = "out_of_range"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"


class RuntimeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    vehicle_id: str
    trip_id: str | None = None
    protocol: Protocol
    source_dataset: str | None = None
    source_timestamp: str
    replay_timestamp: str | None = None
    provenance: Provenance
    quality_flag: QualityFlag = QualityFlag.OK


class SignalSample(RuntimeMessage):
    message_type: Literal["signal_sample"] = "signal_sample"
    signal: str
    value: float | int | bool | None
    unit: str

    @field_validator("value")
    @classmethod
    def finite_number(cls, value):
        if isinstance(value, float) and not (-float("inf") < value < float("inf")):
            raise ValueError("signal value must be finite")
        return value


class DiagnosticEvent(RuntimeMessage):
    message_type: Literal["diagnostic_event"] = "diagnostic_event"
    event_type: str
    event_code: str | None = None
    description: str | None = None
    severity: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class VehiclePropertyUpdate(RuntimeMessage):
    message_type: Literal["vehicle_property_update"] = "vehicle_property_update"
    property_id: int
    property_name: str
    value: Any = None
    unit: str | None = None
    status: Literal["available", "unavailable", "invalid", "error"] = "available"


class ProtocolStatus(RuntimeMessage):
    message_type: Literal["protocol_status"] = "protocol_status"
    status: Literal["available", "unavailable", "connected", "disconnected", "error"]
    detail: str | None = None


class LogEvent(RuntimeMessage):
    message_type: Literal["log_event"] = "log_event"
    buffer_set: str
    buffer_name: str
    event_code: str
    message: str
    severity: str | None = None
    component: str | None = None
    unknown_fields: list[str] = Field(default_factory=list)
    timestamp_components: dict[str, int] = Field(default_factory=dict)
    timestamp_year: int | None = None


RuntimeRecord = (
    SignalSample | DiagnosticEvent | VehiclePropertyUpdate | ProtocolStatus | LogEvent
)
