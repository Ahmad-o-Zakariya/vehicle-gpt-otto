# Local SLM planner

## Verified implementation

The planner uses a loopback-only llama.cpp OpenAI-compatible endpoint with a
small constrained semantic schema, Pydantic validation and one bounded retry.
The model emits only intent, domain, operation and temporal scope. Deterministic
resolution binds the selected vehicle, approved signals, events and time window
into a typed plan. TRACE coverage and the independent verifier control the
final answer; the model does not write answer prose or execute SQL.

Local inference is verified with the pinned GGUF and llama.cpp build 12180
(`bcb015287`, v0.9.0-dev). The file is 1,280,835,808 bytes and SHA-256 is
`cbb39d5102a6e6ef9675912b1c21d02335f4374c6bc267faa6cb96d7987d4a7b`. The
actual five-case report is
[`artifacts/evaluation/slm_case_study.json`](../artifacts/evaluation/slm_case_study.json):
all five requests used `llama.cpp local SLM`, returned HTTP 200, produced
validated plans and passed TRACE verification. The BMW precursor case returned
E1 with 724 evidence references and synthetic provenance; the other four cases
correctly returned E0 with no evidence references. CPU API latency in this run
was 0.2–407.6 ms (the precursor case is the high end); this is a single smoke
run, not a performance benchmark.

The GGUF was tested in explicit CPU-only mode because this Codex execution
context could not access an NVIDIA device or driver. The user-provided target
host reports an RTX 3050 4 GB, but GPU offload and VRAM use are not verified by
this run. The repository launcher defaults to automatic layer selection and
reports the selected mode; set `LLAMA_GPU_LAYERS=0` to explicitly request CPU.
No `llama-cli` generation result is claimed: an early standalone constrained
generation attempt failed, while the server API path above passed.

## Run it

Pinned model metadata is in `configs/model_candidate.json`. The upstream model
is Qwen/Qwen3.5-2B revision
`15852e8c16360a2fea060d615a32b45270f8a8fc`; the third-party Unsloth GGUF is
revision `b6d78642766d0457789548ee826aaf8a4306b14f`, Q4_K_M. Check provenance
and license terms before redistribution.

```sh
scripts/run_llama_server.sh              # GPU auto-detection; loopback only
scripts/run_backend.sh                   # omit VEHICLEGPT_DEMO_MODE for SLM
scripts/run_ui.sh
.venv/bin/python scripts/run_slm_case_study.py
```

The runner refuses demo mode and records raw model output, semantic extraction,
validated plan, TRACE result, verifier status and latency. `run_benchmark.py`
is a separate deterministic fixture benchmark and must not be cited as SLM
accuracy or a fair baseline comparison. Host capability and dependency versions
are recorded in `docs/ENVIRONMENT_VALIDATION.md`.
