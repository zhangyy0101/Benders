from __future__ import annotations
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from pilot_benchmark_suite import audit_suite
def main():
    p=argparse.ArgumentParser();p.add_argument("suite_dir");a=p.parse_args();r=audit_suite(a.suite_dir);print(f"audit {r['status']}: {r['instance_count']} instances");return 0 if r["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())
