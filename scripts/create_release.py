#!/usr/bin/env python3
"""Create a versioned, conditional internal release without rebuilding data."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sqlite3, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'
DB = ROOT / 'data/processed/vehicle_gpt.sqlite'
OUT = ROOT / f'data/releases/v{VERSION}'

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    return h.hexdigest()

def json_file(path): return json.loads(path.read_text())
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--version',default=VERSION)
    args=ap.parse_args()
    if args.version != VERSION:
        ap.error(f'this reviewed release is {VERSION}; update release metadata before using another version')
    out=ROOT/f'data/releases/v{args.version}'
    if out.exists(): ap.error(f'release already exists: {out}')
    acceptance=json_file(ROOT/'data/manifests/acceptance_report.json')
    validation=json_file(ROOT/'data/manifests/validation_report.json')
    if acceptance.get('overall_verdict') != 'CONDITIONAL ACCEPT' or validation.get('status') != 'passed':
        ap.error('acceptance or validation report does not permit release')
    required=['docs/DATA_CARD.md','docs/DATASET_ACCEPTANCE_AUDIT.md','docs/QUESTION_COVERAGE.md','docs/DATA_QUALITY_REPORT.md','docs/REPRODUCIBILITY_GUIDE.md','data/manifests/raw_files.json','data/manifests/derived_output_hashes.json','data/manifests/acceptance_report.json','data/manifests/validation_report.json']
    missing=[p for p in required if not (ROOT/p).is_file()]
    if missing: ap.error('required release materials missing: '+', '.join(missing))
    out.mkdir(parents=True)
    try:
        dbout=out/'vehicle_gpt.sqlite'
        # Reflink when available; otherwise a normal independent copy. Never hard-link mutable working data.
        cp=subprocess.run(['cp','--reflink=auto','--sparse=always',str(DB),str(dbout)],capture_output=True,text=True)
        if cp.returncode: raise RuntimeError(cp.stderr.strip() or 'database copy failed')
        shutil.copy2(ROOT/'data/processed/ground_truth/ground_truth.sqlite',out/'ground_truth.sqlite')
        shutil.copy2(ROOT/'data/processed/ground_truth/injections.json',out/'injections.json')
        for item in required:
            dest=out/item
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/item,dest)
        for p in out.rglob('*'):
            if p.is_file(): p.chmod(0o444)
        con=sqlite3.connect(f'file:{dbout}?mode=ro',uri=True)
        counts={t:con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in ['canonical_measurement','overlay_event','overlay_sample','derived_1hz','trip_rollup','event_window','deviation_flag','vehicle_registry','trip_registry']}
        con.close()
        manifest={
          'release':'VehicleGPT Dataset','version':args.version,'release_status':'CONDITIONAL INTERNAL SNAPSHOT','created_utc':datetime.now(timezone.utc).isoformat(),
          'database':'vehicle_gpt.sqlite','database_sha256':sha256(dbout),'ground_truth_sha256':sha256(out/'ground_truth.sqlite'),'injections_json_sha256':sha256(out/'injections.json'),
          'counts':counts,'validation':validation,'acceptance_verdict':acceptance['overall_verdict'],
          'derived_output_hashes':json_file(ROOT/'data/manifests/derived_output_hashes.json'),
          'raw_manifest_sha256':sha256(ROOT/'data/manifests/raw_files.json'),
          'runtime':{'built_with':sys.version,'required':'Python >=3.11,<3.12','target_runtime_verified':False},
          'redistribution':'NOT AUTHORIZED: confirm source-specific data terms before external distribution',
          'limitations':['OpenLKA unix_time repeats within clips; use clip-relative ordering for within-clip analysis.','Python 3.11 target environment not tested.','Conditional acceptance is not a claim of full case-study coverage.']
        }
        mp=out/'release_manifest.json'; mp.write_text(json.dumps(manifest,indent=2)+'\n'); mp.chmod(0o444)
        print(json.dumps({'release':str(out.relative_to(ROOT)),'version':args.version,'database_sha256':manifest['database_sha256'],'counts':counts},indent=2))
    except Exception:
        shutil.rmtree(out,ignore_errors=True)
        raise
if __name__=='__main__': main()
