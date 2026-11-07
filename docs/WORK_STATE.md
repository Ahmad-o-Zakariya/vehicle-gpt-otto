# Work state

## Current phase
Final v0.2.0 acceptance and development freeze. Dataset v0.1.0 remains immutable.

## Completed
- Verified llama.cpp build 12180 (`bcb015287`, v0.9.0-dev), local Qwen3.5-2B Q4_K_M GGUF size/hash, and CPU-only server inference.
- Ran all five case studies through live SLM → FastAPI → typed resolver → TRACE → verifier. 5/5 HTTP 200 and verifier passed; four E0 unsupported answers, one synthetic precursor E1 with 724 evidence references. Report: `artifacts/evaluation/slm_case_study.json`.
- Fixed strict semantic-schema test fixtures. Focused tests: 34 passed, 1 skipped. Full unrestricted regression: 52 passed, 1 skipped, 5 subtests passed.
- Focused Ruff clean. `run_system_validation.py` passed with read-only repository, 5 hostile SQL rejections and resolved engine evidence. `run_trace_validation.py` passed grade and adversarial checks. Development fixture benchmark passed at 1.0 intent/coverage/grade accuracy; it is not model evaluation.
- Streamlit selection/stale-answer behavior was verified in the live UI in the earlier integration session. API and UI launch/run instructions updated.
- No data generation or build command was run. Frozen main/release DB SHA-256: `701c3e1ff3e7eeeeb18bbebf8a4098d46165acf76ac0b4b2a5d8872abc7043ed`. Manifest SHA-256: `e856ae472c70bc702f32a90430774a22d9a7f50cc40085c4546247616fd4405c`.

## Pending
- None. The final read-only release verifier and process cleanup are complete.

## Verified decisions
- Actual model semantic extraction and application workflow pass in CPU-only mode. GPU offload/VRAM is not verified because the NVIDIA device/driver is inaccessible in this execution context.
- SLM-generated SQL/RAG baseline evaluation remains unperformed. Manual read-only SQL/FTS retrieval tests do not satisfy that criterion.
- Protocol classification: CAN decode/virtual transport tested; SOME/IP, VHAL and QNX are simulations; precursor examples are synthetic and do not establish causality.
- The five case-study answers: driving range historical E0; fuel efficiency largest-drop E0 (no validated measure); ADAS yesterday E0 (unaligned wall clock); BMW overheating precursor E1, synthetic-only; city/highway E0 (no validated route labels).
- Full-repo Ruff has 124 legacy/vendor diagnostics; focused application lint is clean. No new dependencies were added.
- Workspace has no Git metadata; do not create release tags. v0.2.0 is a development-complete research prototype with documented acceptance limitations, not production-certified automotive software.

## Blockers / limitations
- GPU target validation and actual-inference SQL/RAG comparisons are not complete; therefore full acceptance is not claimed and no `v1.0.0` tag is appropriate.
- Dataset reuse terms remain unresolved. Native SOME/IP, real VHAL and QNX access are unavailable; SocketCAN/vcan requires host netlink access.

## Exact next action
None. Leave the software frozen; subsequent work is limited to defect correction, security fixes or necessary compatibility maintenance.
