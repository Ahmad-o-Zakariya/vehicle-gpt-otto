#!/usr/bin/env python3
"""Verify a frozen release's file hashes and database integrity read-only."""
import argparse, hashlib, json, sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('release',nargs='?',default='data/releases/v0.1.0'); a=ap.parse_args(); d=(ROOT/a.release).resolve(); m=json.loads((d/'release_manifest.json').read_text())
 checks={'database_sha256':sha(d/'vehicle_gpt.sqlite')==m['database_sha256'],'ground_truth_sha256':sha(d/'ground_truth.sqlite')==m['ground_truth_sha256'],'injections_json_sha256':sha(d/'injections.json')==m['injections_json_sha256']}
 c=sqlite3.connect(f'file:{d/"vehicle_gpt.sqlite"}?mode=ro',uri=True); integrity=c.execute('PRAGMA integrity_check').fetchone()[0]; fk=list(c.execute('PRAGMA foreign_key_check')); checks['sqlite_integrity']=integrity=='ok'; checks['foreign_keys']=not fk
 counts={t:c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in m['counts']}; checks['row_counts']=counts==m['counts']; c.close()
 result={'status':'passed' if all(checks.values()) else 'failed','checks':checks,'integrity':integrity,'foreign_key_violations':len(fk)}
 print(json.dumps(result,indent=2)); return 0 if result['status']=='passed' else 1
if __name__=='__main__': raise SystemExit(main())
