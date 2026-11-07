#!/usr/bin/env python3
"""Fetch the pinned GGUF only when explicitly invoked; verify size and SHA-256."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'configs/model_candidate.json').read_text())
out=ROOT/'models/qwen35-2b'/config['gguf_file']
if out.exists(): raise SystemExit(f"refusing to overwrite existing model: {out}")
out.parent.mkdir(parents=True,exist_ok=True)
url=f"https://huggingface.co/{config['gguf_repository']}/resolve/{config['gguf_revision']}/{config['gguf_file']}"
try:
    with urllib.request.urlopen(url,timeout=60) as response, out.open('xb') as target:
        h=hashlib.sha256(); size=0
        while block:=response.read(8*1024*1024):
            target.write(block); h.update(block); size+=len(block)
    if size!=config['expected_size_bytes'] or h.hexdigest()!=config['expected_sha256']:
        out.unlink(missing_ok=True)
        raise SystemExit(f"model verification failed (size={size}, sha256={h.hexdigest()}); partial file removed")
except Exception:
    out.unlink(missing_ok=True)
    raise
print(json.dumps({'path':str(out.relative_to(ROOT)),'size_bytes':size,'sha256':h.hexdigest(),'verified':True},indent=2))
