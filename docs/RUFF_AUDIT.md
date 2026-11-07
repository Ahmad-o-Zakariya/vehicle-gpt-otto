# Ruff audit and remediation

Machine-readable reports: `artifacts/quality/ruff_report_before.json` and `artifacts/quality/ruff_report_after.json`.

| Measure | Before | After |
|---|---:|---:|
| Repository-wide findings | 124 | 124 |
| Focused application/adapters/engines/planner/API/UI/tests and validation scripts | 0 | 0 |
| Findings removed from repository-wide baseline | — | 0 |

No automatic fixes were applied across the repository. The focused production and test tree had already been formatted and lint-clean before this audit; new remediation files were checked and formatted. Whole-repository count remains unchanged.

## Classification

- **Correctness/runtime risk (45):** `F821` undefined names, all in comma2k19 vendor notebooks and `DATASET/comma2k19-master/utils/orientation.py`. Notebook names may be supplied by interactive cell state; `orientation.py` uses Python-2 `xrange` under Python 3 and is a genuine legacy runtime defect if that helper is called. The vendored dataset/source tree is frozen and this helper is not imported by VehicleGPT runtime. Git history is unavailable, so origin is unknown rather than asserted pre-existing.
- **Security/unsafe implementation (0 Ruff-specific):** The configured Ruff ruleset reports no security-specific diagnostic. Security was audited separately with SQL and TRACE tests; see `artifacts/validation/security_validation_report.json`.
- **Import/type-related (36):** `I001` 21, `F401` 13, `F404` 2. Found in vendor notebooks, scripts, and ingestion/storage files outside the focused Phase 2–6 tree.
- **Maintainability (14):** `F841` 5, `C417` 3, `TRY004` 2, `TRY201` 1, `SIM113` 1, `SIM102` 1, `SIM114` 1.
- **Formatting/style/packaging (27):** `EXE001` 10, `UP017` 4, `UP010` 3, `UP035` 3, `UP032` 2, `UP004` 2, `UP031` 1, `EXE002` 1, `FURB162` 1.
- **Other/unknown origin (2):** `PLW1510` 1 and `SIM115` 1. Both are in project scripts; no Git baseline exists to establish their history.
- **Legacy/unrelated locations:** Findings are in vendored `DATASET/comma2k19-master` notebooks/utilities and dataset build/inspection/ingest/release scripts. No original source or frozen data was changed to silence them.

`artifacts/quality/ruff_report_before.json` was captured before changes in this audit; after report confirms the same 124 total. `git status` cannot run because the workspace is not a Git repository, so commit-level provenance is unavailable.

## Reproduce

```sh
.venv/bin/ruff check . --output-format json
.venv/bin/ruff check src/vehicle_gpt/runtime src/vehicle_gpt/adapters src/vehicle_gpt/repositories src/vehicle_gpt/engines src/vehicle_gpt/trace src/vehicle_gpt/planner src/vehicle_gpt/api src/vehicle_gpt/evaluation ui tests scripts/run_system_validation.py scripts/run_trace_validation.py
```
