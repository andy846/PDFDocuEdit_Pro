"""Repeatable warm local synthetic benchmarks; generation runs in fresh processes."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import fitz

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))


def run(directory,pages):
    from composition.production.resources import peak_memory
    from workflow.engine import execute
    from workflow.extraction import ExtractionSpec, ExtractionStore, Region
    from workflow.model import WorkflowRun, WorkflowSpec
    spec=WorkflowSpec.default()
    spec.node("input").params={"paths":[str(directory/f"source-{pages}.pdf")]}
    spec.node("extract").params=ExtractionSpec([Region(y_mm=15,height_mm=12,remove_label="Account: ",format="digits")]).to_dict()
    spec.node("group").params={"method":"field","field":"Account_No"}
    node=spec.node("overlay")
    before=next(a for a,b in spec.edges if b==node.id)
    after=next(b for a,b in spec.edges if a==node.id)
    spec.edges=[e for e in spec.edges if node.id not in e]+[[before,after]]
    spec.nodes.remove(node)
    spec.node("output").params={"directory":str(directory/f"output-{pages}")}
    started=time.perf_counter()
    result=execute(spec,WorkflowRun(),directory/f"run-{pages}")
    scanned=time.perf_counter()-started
    if result.error:
        raise RuntimeError(result.error)
    with ExtractionStore(result.database) as store:
        store.accept()
    result.accepted=True
    started=time.perf_counter()
    result=execute(spec,result,directory/f"run-{pages}",until="output")
    generated=time.perf_counter()-started
    if result.error or result.output.get("status")!="completed":
        raise RuntimeError(result.error)
    total=scanned+generated
    return {"pages":pages,"envelopes":len(result.groups),"extraction_grouping_seconds":scanned,
            "production_seconds":generated,"total_seconds":total,"pages_per_second":pages/total,
            "peak_memory_bytes":peak_memory(),"output_bytes":Path(result.output["output_pdf"]).stat().st_size,
            "fixture":"Local synthetic A4 text pages; warm cache; one region; no overlay objects"}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",default=str(ROOT/"build"/"workflow-benchmark"))
    parser.add_argument("--pages",nargs="+",type=int,default=[1000,10000])
    parser.add_argument("--child",action="store_true")
    args=parser.parse_args()
    directory=Path(args.directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    if args.child:
        print(json.dumps(run(directory,args.pages[0])))
        return
    from composition.template.model import MM_TO_PT
    results=[]
    for count in args.pages:
        if not 1<=count<=100000:
            parser.error("pages must be 1–100000")
        source=directory/f"source-{count}.pdf"
        if not source.exists():
            with fitz.open() as pdf:
                for index in range(count):
                    page=pdf.new_page(width=210*MM_TO_PT,height=297*MM_TO_PT)
                    page.insert_text((60,65),f"Account: {index//3+1:08}")
                pdf.save(source,deflate=True)
        done=subprocess.run([sys.executable,__file__,"--child","--directory",str(directory),"--pages",str(count)],
                            cwd=ROOT,check=True,capture_output=True,text=True,encoding="utf-8")
        result=json.loads(done.stdout)
        results.append(result)
        print(json.dumps(result),flush=True)
        (directory/"benchmark.json").write_text(json.dumps(results,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
