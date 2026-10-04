"""Targeted, synthetic media-plan benchmark; does not render or submit PDFs."""
import argparse
import json
import tempfile
import time
import tracemalloc
from pathlib import Path

from composition.media.model import default_media
from composition.media.planner import build_print_plan
from composition.media.ticket import export_print_package
from composition.template.model import CompositionError, PageSpec, Template


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records",nargs="+",type=int,default=[1000,10000,50000])
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    results=[]
    for count in args.records:
        template=Template(pages=[PageSpec() for _ in range(3)],media=default_media())
        tracemalloc.start()
        before=time.perf_counter()
        plan=build_print_plan(template,count)
        planning=time.perf_counter()-before
        start=time.perf_counter()
        ticket_status="checked"
        ticket_size=0
        with tempfile.TemporaryDirectory(prefix="media-benchmark-") as directory:
            try:
                export_print_package(directory,plan)
                ticket_size=Path(directory,"default_ticket.jdf").stat().st_size
            except CompositionError as exc:
                ticket_status=str(exc)
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append(dict(records=count,pages=plan.output_pages,planning_seconds=planning,
                            report_seconds=time.perf_counter()-start,python_peak_bytes=peak,
                            stock_sheets=plan.stock_sheets,ticket_bytes=ticket_size,ticket_status=ticket_status))
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps({"fixture":"synthetic, 3 A4 pages / record, 3 alternating stocks, simplex",
        "scope":"Physical planning + disk-backed reports + JDF; not PDF rendering, hardware validation or a throughput guarantee",
        "results":results},indent=2),encoding="utf-8")
    print(str(args.report.resolve()))


if __name__=="__main__":
    main()
