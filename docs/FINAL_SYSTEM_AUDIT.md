# Final VehicleGPT system audit

Audit executed 2026-11-07 in the Linux Codex workspace. The workspace root has no `.git` metadata, so a historical diff/origin audit is unavailable. `docs/WORK_STATE.md` records the pinned data hashes. No dataset build or data write was run.

## Acceptance matrix

| Component | Status | Evidence and boundary |
|---|---|---|
| CAN | PARTIAL | Verified project DBC decoding against 100 source frames and Hypothesis encode/decode plus python-can virtual transport. SocketCAN/vcan did not run: netlink returns `Operation not permitted`. |
| SOME/IP | SIMULATED | Bounded JSONL Unix socket echo and malformed payload tests pass. No native sidecar source, Boost headers, or vSomeIP libraries; no native service/client run. |
| VHAL | SIMULATED | AOSP property IDs and simulator read/update/status/subscription tests pass. No Android SDK, adb, emulator, or real VHAL. |
| QNX | SIMULATED | Documented five-column parser fixture tests pass, including malformed line and explicit synthetic provenance. No QNX tools or genuine slog2info export found. |
| Runtime interface | PASS | Pydantic message validation and separate runtime SQLite storage tests pass; frozen canonical path is refused. |
| Event engine | PASS | Executed against real operational overlay events; evidence references resolve. |
| Trend engine | PASS | Executed measured fuel-rate signal across 1,822 valid samples; evidence resolves. Irregular cadence is surfaced. |
| Comparison engine | PASS | Executed trip-to-trip measured fuel-rate comparison and gross V×A throughput over two operational trips; city/highway correctly returns unavailable. The reported absolute throughput delta is 2.79268 kWh/trip; this is not signed consumption. |
| Precursor engine | SIMULATED | Multi-event windows and recurrence executed on four development synthetic events; 1,340 references resolve; no causal inference. No measured OEM overheating event established. |
| TRACE grading | PASS | E0/E1/E2/E3/E− rules exercised deterministically. |
| TRACE verifier | PASS | Rejects altered value, missing calculation/ref, unresolved evidence, forged unit/timestamp/vehicle, synthetic relabeling, causal language, contradiction, and prose differing from deterministic renderer. |
| SLM | PASS (CPU) | Pinned local GGUF and llama.cpp build 12180 (`bcb015287`, v0.9.0-dev) ran through the loopback API in CPU-only mode. Five live queries passed TRACE verification. GPU offload remains unverified. |
| Planner | PASS | Five actual SLM semantic outputs became validated typed plans and exercised selected-vehicle binding plus deterministic resolution. |
| FastAPI | PASS | Live process tested health, vehicles, capabilities, query, evidence, events, history, API docs and 404 behavior. Five case studies returned grounded demo-fixture results. |
| Streamlit | PASS | Live app returned HTTP 200. Browser test ran a fuel-rate query and displayed answer, evidence, coverage, and rendered Plotly time-series chart. No accessibility audit. |
| SLM-to-SQL | BLOCKED | Read-only SQL and hostile-input protections were tested, but no SLM-generated SQL baseline was evaluated. |
| RAG | PARTIAL | FTS5/BM25 retrieved lexical context and IDs. No SLM-grounded RAG generation comparison was evaluated; this is not dense-vector RAG. |
| TRACE benchmark | PARTIAL | Five development fixtures achieved 1.0 exact intent/coverage/grade agreement and grounded responses. Not held-out/model accuracy. |
| Security | PASS | Read-only repository, ground-truth path denial, query-only database, SQL authorizer and verifier adversarial tests pass. |
| Dataset | PASS | Final release verification passed database/sidecar hashes, SQLite integrity, foreign-key and row-count checks. v0.1.0 remained unchanged. |

## End-to-end case results

`artifacts/evaluation/slm_case_study.json` records five live FastAPI queries in local SLM mode. The earlier demo workflow is separately preserved in `artifacts/evaluation/end_to_end_report.json`.

| Case | Vehicle | Engine | Grade | Verifier | Interpretation |
|---|---|---|---|---|---|
| Two-week range | ved:455 | trends | E0 | grounded | Historical source data cannot establish the requested recent decline. |
| Fuel efficiency | ved:119 | unsupported | E0 | grounded | No validated fuel-efficiency or largest-drop calculation is available. |
| ADAS yesterday | OpenLKA clip | events | E0 | grounded | Replay timestamps cannot be safely aligned with yesterday. |
| Overheating precursor | BMW i3 | precursors | E1 | grounded | Synthetic development warning case; association only, not causation. |
| City/highway | ved:455 | unsupported | E0 | grounded | No validated route-class labels or matched segments. |

All five requests returned HTTP 200, produced validated typed plans and passed the independent verifier. The precursor case returned 724 evidence references, with synthetic provenance. Four unsupported queries returned no references and correctly grounded E0 answers.

## Corrective changes during this audit

- `/query` now applies the UI-selected vehicle to the typed plan. This fixed a mismatch between visible vehicle context and backend analysis.
- Coverage preflight now allows unsupported wall-clock requests to reach the deterministic fail-closed response; ADAS “yesterday” returns E0 instead of HTTP 422 for missing ADAS signals.
- TRACE validates resolved signal/unit/timestamp/provenance/identity, disallows uncited evidence, requires calculation references for numeric values, and checks claim text against a deterministic renderer.
- Direct SQL and FTS constructors reject paths inside `ground_truth`.
- Streamlit deprecated width arguments were replaced with `width="stretch"` after the live server warning.
- Added reproducible read-only scripts `scripts/run_system_validation.py` and `scripts/run_trace_validation.py`.

## Remaining boundaries

No real CAN interface, native SOME/IP, Android emulator, QNX logging system, fair comparative generation benchmark, held-out metrics, GPU/RAM inference profile, or causal experiment was run. CPU model inference and the five-case application workflow did run; see [host readiness](HOST_INTEGRATION_READINESS.md) for hardware boundaries. Dataset reuse terms remain unresolved. Full-repository Ruff findings are unchanged and confined to legacy/vendor areas; the application-focused Ruff run passes.

## Final development-freeze acceptance

**Disposition:** frozen research prototype delivered; the full definition of done is **not met** because GPU-target validation and SLM-based SQL/RAG baseline comparison remain unverified, and protocol adapters include simulations. Actual local CPU inference and the SLM–FastAPI–TRACE application path did pass. This is not production-certified automotive software. No `v1.0.0` tag was created; this workspace has no Git metadata, and the release acceptance gate did not pass.

| # | Acceptance criterion | Result | Evidence / limitation |
|---:|---|---|---|
| 1 | Four protocol adapters implemented, tested, accurately classified | PASS | CAN decode/virtual transport tested; SOME/IP, VHAL and QNX remain explicitly simulated. |
| 2 | Four deterministic engines against operational data where evidence permits | PARTIAL | Event, trend and comparison engines ran on operational records. Precursor demonstration uses development synthetic warnings; no measured overheating precursor was established. |
| 3 | TRACE grading, coverage and independent verifier tests | PASS | Grade rules and ten adversarial verifier cases passed. |
| 4 | Actual local SLM inference on target development machine | PARTIAL | Actual CPU inference passed on the local development execution environment. Target RTX 3050 GPU offload could not be verified. |
| 5 | Typed plans generated and validated | PASS | Five actual SLM semantic outputs resolved into validated typed plans. |
| 6 | Complete FastAPI–SLM–TRACE–Streamlit workflow | PASS (CPU) | Live FastAPI queries used the SLM and TRACE; Streamlit was exercised against the application during the same integration session. GPU mode is not verified. |
| 7 | Five case studies through the application | PASS | Five live SLM queries returned HTTP 200 and passed the verifier; results are in `artifacts/evaluation/slm_case_study.json`. |
| 8 | Unsupported questions return insufficient-evidence answers | PASS | Unsupported range, wall-clock ADAS and city/highway requests returned grounded E0 responses. |
| 9 | Actual-inference SQL and RAG baselines compared with TRACE | BLOCKED | Manual read-only SQL and FTS5/BM25 smoke checks ran; SLM-generated baseline comparison remains unperformed. |
| 10 | Security and ground-truth isolation tests | PASS | Read-only enforcement, five hostile SQL inputs, ground-truth path denial and TRACE adversarial checks passed. |
| 11 | Regression tests pass | PASS | Final unrestricted run: 52 passed, 1 optional integration test skipped, 5 subtests passed. |
| 12 | Frozen dataset v0.1.0 unchanged | PASS | Final release verification passed all hashes, SQLite integrity, foreign-key and row-count checks. |
| 13 | Setup, execution, validation and benchmark instructions reproducible | PASS | README and linked environment, testing, planner and evaluation records provide pinned commands and versions. |
| 14 | Remaining limitations documented | PASS | This report, the host-readiness matrix and component audit record blockers and simulation boundaries. |

### Final freeze checks

- Final development benchmark: `artifacts/benchmark/dev_benchmark.json`; five deterministic fixture cases, intent/coverage/grade accuracy 1.0, all answers grounded. This is separate from model inference and is not held-out or baseline-comparison evidence.
- Final quality checks: focused Ruff clean; full-repository Ruff remains at 124 legacy/vendor findings. Lock/dependency checks previously resolved 60 packages and found all 64 installed packages compatible.
- Final dataset verification: passed; SQLite integrity `ok`; zero foreign-key violations. Main/release database SHA-256 is `701c3e1ff3e7eeeeb18bbebf8a4098d46165acf76ac0b4b2a5d8872abc7043ed`. Release and dataset manifest SHA-256 is `e856ae472c70bc702f32a90430774a22d9a7f50cc40085c4546247616fd4405c`.
- Live SLM report: `artifacts/evaluation/slm_case_study.json`; pinned GGUF hash verified; llama.cpp v0.9.0-dev build 12180. All five requests passed validation and verification in CPU mode; GPU offload was unavailable in this execution context.
- Package metadata version is `0.2.0`; runtime versions are in [environment validation](ENVIRONMENT_VALIDATION.md). Model/runtime evidence is in [SLM planner](SLM_PLANNER.md).
- No implementation changes are planned after this freeze. Restrict subsequent work to defect correction, security fixes and necessary compatibility maintenance; treat substantial capabilities as a separately scoped project.
