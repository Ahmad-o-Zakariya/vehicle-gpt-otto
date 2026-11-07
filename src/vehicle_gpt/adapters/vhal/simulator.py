from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vehicle_gpt.runtime.messages import (
    Protocol,
    Provenance,
    QualityFlag,
    VehiclePropertyUpdate,
)

ROOT = Path(__file__).resolve().parents[4]
PROPERTIES = json.loads((ROOT / "configs/vhal_properties.json").read_text())


@dataclass(frozen=True)
class PropertyDefinition:
    property_id: int
    name: str
    data_type: str
    unit: str
    access: str
    change_mode: str
    area: str
    availability: str


DEFINITIONS = {
    p["name"]: PropertyDefinition(
        p["id"],
        p["name"],
        p["data_type"],
        p["unit"],
        p["access"],
        p["change_mode"],
        p["area"],
        p["availability"],
    )
    for p in PROPERTIES["properties"]
}


class VhalSimulator:
    """In-memory property simulator with subscription-style async updates."""

    def __init__(self, vehicle_id: str = "vhal:simulator"):
        self.vehicle_id = vehicle_id
        self._values: dict[str, tuple[Any, str, int]] = {}
        self._subscribers: set[asyncio.Queue] = set()

    def update(
        self,
        name: str,
        value: float | None,
        *,
        status: str = "available",
        timestamp_ns: int | None = None,
    ) -> VehiclePropertyUpdate:
        definition = DEFINITIONS.get(name)
        if definition is None:
            raise KeyError(f"unsupported AOSP VHAL property: {name}")
        if status not in {"available", "unavailable", "invalid", "error"}:
            raise ValueError("invalid VHAL status")
        if (
            definition.data_type == "float"
            and value is not None
            and not isinstance(value, (int, float))
        ):
            raise TypeError(f"{name} expects a float value")
        if status == "available" and value is None:
            raise ValueError("available property requires a value")
        now_ns = timestamp_ns if timestamp_ns is not None else time.monotonic_ns()
        self._values[name] = (value, status, now_ns)
        msg = VehiclePropertyUpdate(
            vehicle_id=self.vehicle_id,
            protocol=Protocol.VHAL,
            source_timestamp=str(now_ns),
            replay_timestamp=str(now_ns),
            provenance=Provenance.SYNTHETIC,
            quality_flag={
                "available": QualityFlag.OK,
                "unavailable": QualityFlag.UNAVAILABLE,
                "invalid": QualityFlag.INVALID,
                "error": QualityFlag.MALFORMED,
            }[status],
            property_id=definition.property_id,
            property_name=name,
            value=value,
            unit=definition.unit,
            status=status,
        )
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass
        return msg

    def get(self, name: str) -> VehiclePropertyUpdate:
        if name not in DEFINITIONS:
            raise KeyError(name)
        if name not in self._values:
            return self.update(name, None, status="unavailable")
        value, status, timestamp_ns = self._values[name]
        return self.update(name, value, status=status, timestamp_ns=timestamp_ns)

    async def subscribe(
        self, max_queue: int = 100
    ) -> AsyncIterator[VehiclePropertyUpdate]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
