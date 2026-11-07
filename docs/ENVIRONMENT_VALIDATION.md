# Environment validation

Validated in the current Codex workspace execution environment on 2026-11-07. This does not prove what is available to an unsandboxed physical host process.

| Item | Observed |
|---|---|
| OS/runtime | Linux x86_64, kernel `7.0.0-42-generic`, Python `3.14.4`; project `.venv` also Python 3.14.4 |
| uv | `0.13.7` was available during environment setup; this shell invocation lacks `uv` on PATH. Locked environment is `.venv`. |
| FastAPI / Pydantic / Streamlit | `0.162.0` / `2.14.3` / `1.67.0` |
| Plotly / NumPy / Pandas | `6.9.0` / `2.5.4` / `3.1.1` |
| python-can / cantools | `4.6.1` / `40.7.1` |
| pytest / Hypothesis / Ruff | `9.2.0` / `6.170.15` / `0.17.4` |
| Dependency consistency | `uv pip check --python .venv/bin/python`: all installed packages compatible |
| Imports | FastAPI, Pydantic, Streamlit, Plotly, NumPy, Pandas, CAN stack, pytest and Hypothesis import successfully |
| Storage | SQLite stdlib; API repository opens read-only. FTS5 baseline successfully initializes. |
| C++/CMake | GCC/G++ 15.2.0 and CMake 4.2.3; standalone C++20 syntax compile passed. |
| Disk | ~224 GiB free on project filesystem; ~4 GiB free in `/tmp` at audit time |
| Memory | `/proc/meminfo`: ~14.5 GiB total, ~9.0 GiB available; swap ~4 GiB total and nearly exhausted |
| GPU | `nvidia-smi` fails to communicate with the driver; no `/dev/nvidia*` visible. GPU offload was not tested. |
| llama.cpp / SLM | Local llama.cpp build 12180 (`bcb015287`, v0.9.0-dev) and pinned Qwen3.5-2B Q4_K_M GGUF were present. CPU-only loopback API inference passed all five application cases; GPU was inaccessible in this execution context. |
| Android/QNX | `adb`, `slog2info` and `qcc` absent |
| Native libraries | Boost headers and vSomeIP headers/pkg-config package absent; `native/` source directory absent |

Python 3.14.4 is the only tested runtime. Dependencies import and pass tests on 3.14.4. Python 3.11 compatibility is not claimed or tested; package metadata deliberately targets `>=3.14,<3.15`. No separate compatibility environment was created.

The `httpx2` package is absent, so Starlette `TestClient` is unavailable. API verification used actual Uvicorn processes and HTTP requests. The five-case live SLM report and model/runtime identifiers are recorded in `artifacts/evaluation/slm_case_study.json` and `configs/model_candidate.json`. Current sandboxed full-suite runs may be unable to bind AF_UNIX sockets (`EPERM`); run the documented suite in an unrestricted local environment for that integration check.
