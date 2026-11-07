# Repository State — Initial Inventory

**Inspected:** 2026-11-06 (Asia/Kolkata)

## Workspace

- Root: `/home/arcues/Projects/OTTO`.
- No tracked repository is initialized: `.git/` is an empty directory and `git status` reports that the workspace is not a Git repository.
- No `AGENTS.md`, project documentation, source package, tests, or build configuration was present at inspection.
- The `docs/` and `manifests/` paths in this report were created for the dataset work.
- Supplied data remains at its existing paths. The VED archives were read and extracted only to `/tmp/ved_inventory` for analysis.

## Specification sources

- Authoritative challenge: `1790163819038-Teliport S4_Case Study and Submission Template/Case Study 5_TBU_Vehicle Information using On-Device SLM or LLM.pdf` (3 pages; extracted and read fully).
- TRACE concept deck: `TRACE_Team_OTTO_Telipport_S4_v3.pptx.pdf` (2 pages; extracted and read fully). The original TRACE `.pptx` is not present. The separate Teliport submission template `.pptx` is present.
- Other supplied reference files include `2505.09092v1.pdf`, `Research.pdf`, `TRACE_ VehicleGPT deck.html`, and the submission-template archive. They are not the Case Study 5 source of truth.

The Case Study requires a local vehicle assistant, multiple vehicle data sources, searchable history, and embedded constraints. Its evaluation criteria are qualitative; it specifies no numeric scoring weights. The TRACE deck describes an illustrative architecture and targets, not measured capabilities.

## Runtime and host snapshot

- `python3`: 3.14.4. Python 3.11 was not verified as installed during initial inspection.
- Visible host resources: 12 logical CPUs, 14 GiB RAM, 247 GiB disk available at inspection. These are host resources, not target-device results.
- `taskset` and `libarchive.so.13` are available. Docker, `7z`, `pandas`, `numpy`, `duckdb`, `pyarrow`, `openpyxl`, `pytest`, and `scipy` were not detected. Python's `yaml` module is available.
- VED 7z archives were read using the available libarchive library; no source archive was modified.

## Existing project content

- `DATASET/VED-master/`: source README, Apache 2.0 license, two dynamic 7z archives, two static vehicle registries.
- `DATASET/Measurement Data/`: TUM BMW i3 measurement CSVs and trip overview workbook.
- `DATASET/Simulation Data/`: separate TUM simulation CSV/MAT files.
- `DATASET/comma2k19-master/`: one sample route/segment, raw and processed logs, video/pose data, README and MIT-licensed repository files.
- `DATASET/OpenLKA-main/`: README, project page assets, and local failure sample CSV/JSON/image files.
- No generated database, loaders, canonical schema, tests, or derived data existed at initial inspection.

## Phase 1 runtime enforcement check

- `scripts/run_limited.sh` was exercised with a Python process: it received CPU affinity `[0, 1]` and `RLIMIT_AS=(2147483648, 2147483648)`.
- `systemd-run --user --scope` failed because the user scope bus is unavailable/operation is not permitted. Docker is absent. The runner therefore enforces CPU affinity and virtual address space only; it does not guarantee a 2 GiB resident-memory limit or CPU quota.
- The raw manifest generation completed over 1,014 files (1,078,275,294 bytes); every entry has a SHA-256 checksum. Source files were only read.
