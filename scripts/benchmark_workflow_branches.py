"""Repeatable fresh-process branch benchmarks; synthetic local data and templates."""
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


def run(count,production=False):
    from composition.production.resources import peak_memory
    from composition.template.model import Element, Template
    from composition.template.serializer import save_project
    from workflow.branch_engine import approve_routes, execute_routes, prepare_routes, rows
    from workflow.branch_graph import add_route
    from workflow.model import WorkflowSpec
    with tempfile.TemporaryDirectory(prefix="br-bench-") as temp:
        root=Path(temp)
        template=save_project(Template(elements=[Element(value="{{Name}} / {{WorkflowSeq}}")]),root/"letter.pdcx")
        model=WorkflowSpec.branched_mail_merge()
        model.node("route").params["routes"]=[{"id":"letters","name":"Type A","fallback":False,
            "condition":{"conditions":[{"field":"Scheme","operator":"eq","value":"A"}]}}]
        model=add_route(model,"Type B",{"conditions":[{"field":"Scheme","operator":"eq","value":"B"}]})
        for path in model.execution_plan().branches.values():
            path[0].params["path"]=str(template)
        items=[]
        for source in range(3):
            file=root/f"data{source}.csv"
            with file.open("w",encoding="utf-8",newline="") as stream:
                stream.write("Name,Scheme\n")
                for record in range(source,count,3):
                    stream.write(f"Customer {record:08d},{'A' if record%2 else 'B'}\n")
            items.append({"id":f"source_{source}","path":str(file),"options":{}})
        model.node("for_each").params["items"]=items
        started=time.perf_counter()
        checked=prepare_routes(model,root/"work")
        checked_seconds=time.perf_counter()-started
        if checked["routed"]!=count or any(j["status"]!="Needs review" for j in checked["jobs"]):
            raise RuntimeError("Benchmark routing/preflight failed: "+str(checked["jobs"]))
        if rows(model,checked,root/"work")["total"]!=count:
            raise RuntimeError("Evidence reconciliation failed")
        generation_seconds=0
        generated_pages=0
        output_bytes=0
        if production:
            approve_routes(model,checked,[j["id"] for j in checked["jobs"]])
            started=time.perf_counter()
            completed=execute_routes(model,checked,root/"work",root/"output")
            generation_seconds=time.perf_counter()-started
            if completed["status"]!="Completed":
                raise RuntimeError("Benchmark production failed")
            for entry in completed["jobs"]:
                result=entry["batch"]["jobs"][0]["result"]
                generated_pages+=result["generated_pages"]
                output_bytes+=result["output_size"]
        return dict(records=count,source_files=3,branches=2,check_seconds=checked_seconds,
                    check_records_per_second=count/checked_seconds,generation_seconds=generation_seconds,
                    generated_pages=generated_pages,output_bytes=output_bytes,peak_memory_bytes=peak_memory(),
                    fixture="Synthetic local CSV; two template branches sharing a one-page text layout; full routing, snapshots and font/rule preflight; no network, CJK, image-heavy or printer guarantee")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--records",type=int,nargs="+",default=[1000,10000,50000])
    parser.add_argument("--production",action="store_true")
    parser.add_argument("--child",action="store_true")
    parser.add_argument("--output",default=str(ROOT/"build"/"workflow-branch-benchmark.json"))
    args=parser.parse_args()
    if any(not 3<=count<=1000000 for count in args.records):
        parser.error("Use 3–1,000,000 records")
    if args.child:
        print(json.dumps(run(args.records[0],args.production)))
        return
    values=[]
    for count in args.records:
        cmd=[sys.executable,__file__,"--child","--records",str(count)]
        if args.production:
            cmd.append("--production")
        process=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",check=True,cwd=ROOT)
        value=json.loads(process.stdout)
        print(json.dumps(value),flush=True)
        values.append(value)
    target=Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(values,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
