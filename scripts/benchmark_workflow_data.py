"""Fresh-process data workflow benchmarks; synthetic local text, no rendered PDFs."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def run(count):
    from composition.production.resources import peak_memory
    from workflow.transforms import snapshot, transform
    with tempfile.TemporaryDirectory(prefix="wf-bench-") as directory:
        root=Path(directory)
        started=time.perf_counter()
        source=snapshot(((n,{"Id":f"{n:08}","Name":f" Name {n} ","Amount":str(n%97)}) for n in range(1,count+1)),
                        ["Id","Name","Amount"],root/"input.sqlite")
        cleaned=transform(source,root/"clean.sqlite","clean_fields",{"operations":[{"field":"Name","operation":"trim"}]})
        result=transform(cleaned,root/"sort.sqlite","sort_records",{"keys":[{"field":"Amount","type":"number"}]})
        elapsed=time.perf_counter()-started
        return {"records":count,"seconds":elapsed,"records_per_second":count/elapsed,"peak_memory_bytes":peak_memory(),
            "output_bytes":result.path.stat().st_size,"fixture":"Synthetic local text; SQLite input, trim and numeric stable sort; fresh process; no PDF rendering"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--records",nargs="+",type=int,default=[1000,10000,50000])
    parser.add_argument("--output",default=str(ROOT/"build"/"workflow-data-benchmark.json"))
    parser.add_argument("--child",action="store_true")
    args=parser.parse_args()
    if any(not 1<=n<=1000000 for n in args.records):
        parser.error("Use 1–1,000,000 records.")
    if args.child:
        print(json.dumps(run(args.records[0])))
        return
    results=[]
    for count in args.records:
        completed=subprocess.run([sys.executable,__file__,"--child","--records",str(count)],
            capture_output=True,text=True,encoding="utf-8",check=True,cwd=ROOT)
        result=json.loads(completed.stdout)
        results.append(result)
        print(json.dumps(result),flush=True)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(results,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
