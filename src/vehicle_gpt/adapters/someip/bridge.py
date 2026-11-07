from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any


@dataclass(frozen=True)
class ProjectService:
    """Local simulator IDs; these are project identifiers, not OEM assignments."""

    service_id: int = 0x7100
    instance_id: int = 0x0001
    method_id: int = 0x0001
    event_id: int = 0x8001
    event_group_id: int = 0x0001


class JsonLineVehicleBridge:
    """Bounded asyncio Unix-socket JSONL simulator, not a SOME/IP implementation."""

    def __init__(self, handler, max_line_bytes: int = 16_384):
        self.handler = handler
        self.max_line_bytes = max_line_bytes

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while raw := await reader.readline():
                if len(raw) > self.max_line_bytes:
                    writer.write(b'{"error":"request_too_large"}\n')
                    await writer.drain()
                    break
                try:
                    request = json.loads(raw)
                    if not isinstance(request, dict) or set(request) - {
                        "method",
                        "params",
                        "request_id",
                    }:
                        raise ValueError("invalid request shape")
                    response: dict[str, Any] = {
                        "request_id": request.get("request_id"),
                        "result": self.handler(request),
                    }
                except (JSONDecodeError, ValueError, TypeError, KeyError) as exc:
                    response = {
                        "error": {"code": "invalid_request", "message": str(exc)[:256]}
                    }
                writer.write(
                    json.dumps(response, separators=(",", ":")).encode() + b"\n"
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def serve(self, path: str):
        server = await asyncio.start_unix_server(
            self.handle, path=path, limit=self.max_line_bytes + 1
        )
        async with server:
            await server.serve_forever()
