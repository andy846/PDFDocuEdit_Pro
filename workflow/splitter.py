"""Split a validated production PDF, then publish the checked set atomically."""
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path

from composition.engine.assets import qpdf_executable
from composition.production.generator import check_cancel
from composition.production.model import new_job_id
from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.pdf_io import validate_pdf_file


def qpdf_select(source, ranges, target, is_cancelled=None):
    if any("\n" in str(value) or "\r" in str(value) for value in (source,ranges,target)):
        raise CompositionError("PDF paths and page selections cannot contain line breaks.")
    args=Path(target).with_suffix(".args")
    args.write_text("\n".join(["--empty","--pages",str(source),ranges,"--",str(target)])+"\n",encoding="utf-8")
    options={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
    process=subprocess.Popen([str(qpdf_executable()),"@"+str(args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,**options)
    try:
        while True:
            check_cancel(is_cancelled)
            try:
                stdout,stderr=process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise CompositionError((stderr or stdout).decode("utf-8",errors="replace")[-2000:])
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        args.unlink(missing_ok=True)


def split_composed(result, source, partitions, output_dir, pages_per_record, *, is_cancelled=None, progress=None):
    root=Path(output_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    job_id=new_job_id()
    staging=Path(tempfile.mkdtemp(prefix=".split-"+job_id+"-",dir=root))
    final=root/job_id
    files=[]
    try:
        with closing(sqlite3.connect(source.path)) as db:
            media_database=Path(result["report_dir"])/"media-plan.sqlite"
            media= json.loads((Path(result["report_dir"])/"media-definition.json").read_text(encoding="utf-8")) if media_database.is_file() else None
            if media:
                db.execute("ATTACH DATABASE ? AS media_plan",(str(media_database),))
            for index,part in enumerate(partitions,1):
                check_cancel(is_cancelled)
                ranges=[]
                expected_pages=0
                for ordinal, in db.execute("SELECT ordinal FROM partitions WHERE partition_key=? ORDER BY ordinal",(part["key"],)):
                    if pages_per_record:
                        start=(ordinal-1)*pages_per_record+1
                        end=start+pages_per_record-1
                    else:
                        start,end=db.execute("SELECT start,end FROM page_spans WHERE ordinal=?",(ordinal,)).fetchone()
                    ranges.append(f"{start}-{end}")
                    expected_pages+=end-start+1
                pdf=staging/part["name"]
                qpdf_select(result["output_pdf"],",".join(ranges),pdf,is_cancelled)
                validate_pdf_file(pdf,expected_page_count=expected_pages)
                files.append({"output_pdf":str(final/pdf.name),"output_sha256":file_hash(pdf),
                    "records":part["records"],"pages":expected_pages,"key":part["key"]})
                if media:
                    from composition.media.ticket import export_rows
                    from composition.template.serializer import file_hash as digest
                    package=staging/pdf.stem
                    package.mkdir()
                    def media_rows(part=part):
                        file_page=0
                        for (ordinal,) in db.execute("SELECT ordinal FROM partitions WHERE partition_key=? ORDER BY ordinal",(part["key"],)):
                            start,end=((ordinal-1)*pages_per_record+1,ordinal*pages_per_record) if pages_per_record else db.execute("SELECT start,end FROM page_spans WHERE ordinal=?",(ordinal,)).fetchone()
                            for row in db.execute("SELECT * FROM media_plan.pages WHERE file_page BETWEEN ? AND ? ORDER BY file_page",(start,end)):
                                file_page+=1
                                yield [file_page,*row[1:]]
                    files[-1]["media_summary"]=export_rows(package,media,media_rows(),expected_pages,pdf.name,is_cancelled=is_cancelled)
                    shutil.move(pdf,package/pdf.name)
                    files[-1]["output_pdf"]=str(final/pdf.stem/pdf.name)
                    files[-1]["output_sha256"]=digest(package/pdf.name)
                    (package/"job.json").write_text(json.dumps({"job_version":2,"job_id":result["job_id"]+"-"+str(index),
                        "status":"completed","global_job_id":result["job_id"],"records":part["records"],"pages":expected_pages,
                        "output_pdf":pdf.name,"media_summary":files[-1]["media_summary"],"page_mapping":"media-plan.csv",
                        "sequence_policy":"Global production sequence retained; File page rebased to 1"},indent=2),encoding="utf-8")
                with (staging/(pdf.stem+"-source-map.csv")).open("w",encoding="utf-8-sig",newline="") as stream:
                    writer=csv.writer(stream)
                    writer.writerow(["File page","Production record","Source record","Logical page" if media else "Template page"])
                    file_page=0
                    for ordinal,source_id in db.execute("SELECT records.ordinal,source_row FROM records JOIN partitions USING(ordinal) WHERE partition_key=? ORDER BY ordinal",(part["key"],)):
                        count=pages_per_record if pages_per_record else db.execute("SELECT end-start+1 FROM page_spans WHERE ordinal=?",(ordinal,)).fetchone()[0]
                        for page in range(1,count+1):
                            file_page+=1
                            logical=page
                            if media:
                                global_page=(ordinal-1)*pages_per_record+page if pages_per_record else db.execute("SELECT start FROM page_spans WHERE ordinal=?",(ordinal,)).fetchone()[0]+page-1
                                logical=db.execute("SELECT logical_page FROM media_plan.pages WHERE file_page=?",(global_page,)).fetchone()[0]
                            writer.writerow([file_page,ordinal,source_id,logical])
                if progress:
                    progress(index,len(partitions),f"Validating split PDF {index}/{len(partitions)}")
        if sum(f["records"] for f in files)!=source.count or sum(f["pages"] for f in files)!=result["generated_pages"]:
            raise CompositionError("Split reconciliation failed.")
        updated={**result,"job_id":job_id,"output_pdf":files[0]["output_pdf"] if files else "",
                 "generated_files":len(files),"output_files":files,"report_dir":str(final),
                 "output_size":sum((staging/Path(f["output_pdf"]).relative_to(final)).stat().st_size for f in files)}
        if files:
            updated["output_sha256"]=files[0]["output_sha256"]
        updated.update(source_records=source.metadata.get("source_records",source.count),retained_records=source.count,
                       excluded_records=source.metadata.get("source_records",source.count)-source.count)
        if updated.get("glyph_repair_report"):
            updated["glyph_repair_report"]=str(final/Path(updated["glyph_repair_report"]).name)
        for path in Path(result["report_dir"]).glob("*.csv"):
            if path.name=="control.csv":
                continue
            shutil.copyfile(path,staging/path.name)
        parent_log=Path(result["report_dir"])/"job.json"
        if parent_log.is_file():
            shutil.copyfile(parent_log,staging/"composition-job.json")
        for name in ("original-boundaries.json","workflow.json"):
            path=Path(result["report_dir"])/name
            if path.is_file():
                shutil.copyfile(path,staging/name)
        with (staging/"control.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            writer.writerow(["Job ID","Output file","Records / envelopes","Pages","SHA256","Status"])
            for item in files:
                writer.writerow([job_id,item["output_pdf"],item["records"],item["pages"],item["output_sha256"],"completed"])
        from .transforms import export_audit
        export_audit(source,staging)
        (staging/"workflow-data.json").write_text(json.dumps({"input":updated["source_records"],
            "retained":source.count,"excluded":updated["excluded_records"],"outputs":files},indent=2),encoding="utf-8")
        (staging/"job.json").write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding="utf-8")
        check_cancel(is_cancelled)
        os.rename(staging,final)
        return updated
    finally:
        if staging.exists() and staging.resolve().parent==root and staging.name.startswith(".split-"+job_id+"-"):
            shutil.rmtree(staging)
