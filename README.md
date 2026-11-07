# VehicleGPT — TRACE research prototype

Local, evidence-grounded automotive data exploration for the TELIPORT Season 4 case study. The v0.1.0 dataset remains frozen and conditionally accepted for internal development only; the application opens its operational SQLite database read-only.

```text
Streamlit + Plotly → FastAPI → local SLM planner → typed Pydantic plan
                                      ↓
                        coverage → deterministic engines
                                      ↓
                        TRACE claims → independent verifier
                                      ↓
                         grounded answer + evidence
```

Demo mode uses a deterministic fixture planner. SLM mode uses the pinned local Qwen GGUF through llama.cpp; semantic extraction is followed by deterministic typed-plan resolution. Protocol adapters normalize into separate typed runtime storage. Ground truth is not connected to inference, the repository, or the baselines.

## Environment and launch

Python 3.14.4 was used. Exact direct dependencies and transitive resolution are recorded in `pyproject.toml` and `uv.lock`. To recreate the application environment:

```sh
python3.14 -m venv .venv
.venv/bin/pip install uv
UV_CACHE_DIR=/tmp/vehicle-gpt-uv-cache .venv/bin/uv sync --locked --extra dev
```

Run the backend and UI in separate terminals. The backend listens on loopback by default.

```sh
VEHICLEGPT_DEMO_MODE=1 scripts/run_backend.sh # deterministic fixture mode
scripts/run_ui.sh
```

Open `http://127.0.0.1:8501`. For SLM mode, start `scripts/run_llama_server.sh`, then launch the backend without `VEHICLEGPT_DEMO_MODE`. Run `.venv/bin/python scripts/run_slm_case_study.py` to repeat the five live API cases. This environment's verified run used CPU-only llama.cpp; GPU offload remains unverified here. See [SLM planner](docs/SLM_PLANNER.md) for exact model/runtime evidence.

## Tests, benchmark, adapters

```sh
.venv/bin/pytest -q
.venv/bin/python scripts/run_benchmark.py
.venv/bin/python scripts/run_system_validation.py
.venv/bin/python scripts/run_trace_validation.py
.venv/bin/ruff check src/vehicle_gpt/runtime src/vehicle_gpt/adapters src/vehicle_gpt/repositories src/vehicle_gpt/engines src/vehicle_gpt/trace src/vehicle_gpt/planner src/vehicle_gpt/api src/vehicle_gpt/evaluation ui
```

The benchmark is a five-case development smoke run, not a held-out model evaluation. Adapter details and supported setup are in [protocol architecture](docs/PROTOCOL_ADAPTER_ARCHITECTURE.md). SocketCAN/vcan, native vSomeIP, QNX live logs and real VHAL remain unavailable or simulated on this host. Actual local SLM semantic inference and the five-case API workflow passed in CPU mode; GPU offload is unverified.

## Data, limitations, and release

See the [dataset acceptance audit](docs/DATASET_ACCEPTANCE_AUDIT.md), [work state](docs/WORK_STATE.md), [evaluation methodology](docs/EVALUATION_METHODOLOGY.md), and [testing/validation record](docs/TESTING_AND_VALIDATION.md). v0.1.0 is internal-only pending data reuse terms; this work does not rebuild or alter the accepted dataset bundle. Do not use synthetic overlays as observed vehicle faults or interpret temporal precedence as causation.

## Development freeze

This is a frozen research prototype, not a production-certified automotive system. The five live SLM–FastAPI–TRACE cases passed; unsupported questions returned verified E0 answers. The actual-inference SQL/RAG baseline comparison and GPU offload remain unverified, and one AF_UNIX integration test may require an unrestricted host. See the [final acceptance report](docs/FINAL_SYSTEM_AUDIT.md). Full acceptance is not claimed and no `v1.0.0` release tag was created. After the freeze, limit maintenance to defects, security fixes and necessary compatibility work.
