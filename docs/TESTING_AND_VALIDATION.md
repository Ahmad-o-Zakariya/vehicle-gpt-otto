# Testing and validation record

## Commands

Run with the checked-in `.venv` (Python 3.14.4):

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/run_system_validation.py
.venv/bin/python scripts/run_trace_validation.py
.venv/bin/python scripts/run_benchmark.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python -m ruff check src/vehicle_gpt/runtime src/vehicle_gpt/adapters src/vehicle_gpt/repositories src/vehicle_gpt/engines src/vehicle_gpt/trace src/vehicle_gpt/planner src/vehicle_gpt/api src/vehicle_gpt/evaluation ui tests scripts/run_slm_case_study.py scripts/run_benchmark.py scripts/run_system_validation.py scripts/run_trace_validation.py
```

Start llama.cpp and the backend without `VEHICLEGPT_DEMO_MODE`, then run
`.venv/bin/python scripts/run_slm_case_study.py` for live inference acceptance.
It refuses the demo planner and writes `artifacts/evaluation/slm_case_study.json`.

## Current result

- Focused application tests: **34 passed, 1 skipped**. The skipped test is the
  opt-in real-inference test; live inference was separately exercised through
  the API case runner.
- Live SLM/API cases: **5/5 HTTP 200, typed plans valid, TRACE verifier passed**.
  Four unsupported questions were verified E0; the synthetic BMW precursor
  returned E1 with explicit synthetic limitations and 724 references. This is
  one CPU smoke run, not held-out accuracy or a fair baseline benchmark.
- Full regression suite: **52 passed, 1 optional integration test skipped, 5
  subtests passed**. The run required an unrestricted execution context for the
  AF_UNIX bridge test because socket bind is denied in the restricted sandbox.
- The dev fixture benchmark is recorded at
  `artifacts/benchmark/dev_benchmark.json`; its perfect fixture accuracy is not
  an SLM result.
- Prior security/TRACE audit verified evidence tampering rejection, read-only
  database access and ground-truth path isolation. See
  `artifacts/validation/` and `docs/FINAL_SYSTEM_AUDIT.md`.
- Dataset release verifier last passed with SQLite integrity `ok`, zero foreign
  key violations, expected row counts and matching database/sidecar hashes.
  Frozen dataset hashes are in `docs/WORK_STATE.md`.
- Focused Ruff is run as part of finalization. Full-repository Ruff previously
  reported 124 legacy/vendor diagnostics; it is not the application lint gate.

Actual inference SQL and RAG baselines were not evaluated. The CPU run did not
measure GPU offload or VRAM. Native SOME/IP, real VHAL and QNX integrations
remain simulated; SocketCAN/vcan requires host netlink access. This research
prototype is not production-certified automotive software.
