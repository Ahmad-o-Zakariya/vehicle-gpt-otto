#!/usr/bin/env python3
"""Create a checksummed manifest of supplied DATASET source files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(root: Path) -> dict[str, object]:
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        files.append(
            {
                "path": path.relative_to(root.parent).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": checksum(path),
            }
        )
    return {
        "schema_version": 1,
        "source_root": root.relative_to(root.parent).as_posix(),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("DATASET"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/manifests/raw_files.json")
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"source directory does not exist: {root}")
    manifest = build_manifest(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, args.output)
    print(
        f"files={manifest['file_count']} bytes={manifest['total_bytes']} "
        f"output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
