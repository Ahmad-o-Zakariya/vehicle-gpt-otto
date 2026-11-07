# Reproducibility Guide

## Inspect the current snapshot

These commands read the operational SQLite database in read-only mode:

```sh
python3 scripts/inspect_dataset.py summary
python3 scripts/inspect_dataset.py vehicles
python3 scripts/inspect_dataset.py signals --vehicle tum_bmw_i3:bmw_i3
python3 scripts/inspect_dataset.py sample --vehicle tum_bmw_i3:bmw_i3 --signal battery.temperature --limit 20
python3 scripts/inspect_dataset.py quality
python3 scripts/inspect_dataset.py export --help
```

Evaluation labels require explicit opt-in and remain in a separate database:

```sh
python3 scripts/inspect_dataset.py --evaluation-only evaluation-injections --limit 20
```

## Rebuild and validate

The recorded environment is Python 3.14.4; `pyproject.toml` targets Python 3.11. Use a Python 3.11 interpreter for release-grade compatibility verification:

```sh
scripts/run_limited.sh python3.11 scripts/build_pipeline.sh
scripts/run_limited.sh python3.11 scripts/validate_dataset.py
python3.11 -m unittest discover -s tests -v
```

The wrapper limits affinity to two CPUs and virtual address space to 2 GiB. It does not impose a resident-memory limit. Dataset generation is offline and deterministic; the seed/configuration is recorded in the project configuration and reports. Compare `data/manifests/derived_output_hashes.json` after a rebuild. Never rebuild solely to inspect or package the existing dataset.

## Verify the frozen internal release

```sh
scripts/run_limited.sh python3 scripts/verify_release.py
```

The release is an independent SQLite copy. Release files are read-only by mode; do not modify them in place. Create a new version after approved source/configuration changes. The snapshot is conditional and internal-only until data reuse terms and Python 3.11 compatibility are verified.
