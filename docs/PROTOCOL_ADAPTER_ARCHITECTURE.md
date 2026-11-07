# Protocol Adapter Architecture

```mermaid
flowchart LR
  CAN[SocketCAN / python-can] --> CONTRACT[Pydantic runtime messages]
  SOMEIP[vSomeIP, blocked] --> BRIDGE[Bounded local JSONL bridge]
  VHAL[AOSP-aligned simulator] --> CONTRACT
  QNX[slog2info export parser] --> CONTRACT
  BRIDGE --> CONTRACT
  CONTRACT --> STORE[Separate runtime SQLite]
  DATA[Frozen operational SQLite, read-only] --> REPO[Repository] --> ENGINES[Deterministic engines]
  ENGINES --> TRACE[TRACE claims and verifier]
  STORE -. runtime-only ingestion .-> ENGINES
```

Protocol messages use `src/vehicle_gpt/runtime/messages.py` and are appended to
`data/runtime/runtime.sqlite`, never to the frozen canonical DB or release.
Every record retains vehicle/trip identity, protocol, source/replay timestamp,
provenance, quality flag and typed payload. Operational queries open the frozen
DB with SQLite `mode=ro`, `query_only=ON`, and `trusted_schema=OFF`.

**Boundary:** python-can virtual transport and the VHAL simulator are explicit
simulators. Neither is represented as a live vehicle interface. Native vSomeIP
and privileged vcan setup are environment-blocked; see [SOME/IP](SOMEIP_ADAPTER.md)
and [CAN](CAN_ADAPTER.md).
