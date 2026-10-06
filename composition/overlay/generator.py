"""Bounded, cancellable envelope overlay generation and reconciled publication."""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
from contextlib import ExitStack
from itertools import islice
from pathlib import Path

import fitz

from composition.engine.assets import qpdf_executable
from composition.media.planner import PrintPlan, overlay_plan
from composition.pdf_source.source import inspect_source, snapshot_source
from composition.production.generator import JobCancelled, _assemble, check_cancel
from composition.production.model import now
from composition.production.resources import peak_memory
from composition.template.model import CompositionError
from composition.template.serializer import file_hash
from core.pdf_io import validate_pdf_file

from .model import EnvelopeSpec, OverlayResult
from .qc import check_mark
from .renderer import OverlayRenderer, page_records, page_values
from .reports import row, write_summary


def reconcile(result):
    if not (result.input_envelopes==result.processed_envelopes==result.successful_envelopes
            and result.failed_envelopes==0 and result.unverified_envelopes==0 and result.composed_envelopes==result.input_envelopes
            and result.generated_files==1
            and result.copied_source_pages+result.excluded_source_pages==result.source_pages
            and result.rendered_inserted_blanks==result.inserted_blanks
            and result.expected_pages==result.source_pages-result.excluded_source_pages+result.inserted_blanks==result.generated_pages
            and result.expected_barcodes==result.rendered_barcodes==result.decoded_barcodes
            and result.font_scan.get("complete") is True):
        raise CompositionError("RECONCILIATION FAILED: envelope/source/output/blank/barcode counts do not agree.")


def _error_page(result, page):
    result.error_envelope=page.envelope
    result.error_source_page=page.source_page
    result.error_output_page=page.output_page


def generate(job, *, progress=None, is_cancelled=None, external_values=None, additional_reports=None,_defer_media_ticket=False):
    spec=EnvelopeSpec.from_dict(job.project)
    if spec.external_fields and external_values is None:
        raise CompositionError("This overlay requires reviewed Workflow extraction data. Generate it from Workflow.")
    if spec.needs_source_review:
        raise CompositionError("Confirm grouping and review the updated PDF source before generating.")
    if spec.needs_detection_review:
        raise CompositionError("Scan, review and accept mailpiece boundaries before generating this PDF.")
    if not isinstance(job.job_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",job.job_id):
        raise CompositionError("Invalid job identity.")
    if type(job.chunk_size) is not int or not 1 <= job.chunk_size <= 1000 or type(job.auto_repair) is not bool:
        raise CompositionError("Invalid chunk size or automatic font repair flag.")
    output_root=Path(job.output_dir).resolve()
    output_root.mkdir(parents=True,exist_ok=True)
    final=output_root/job.job_id
    failure=output_root/(job.job_id+"-failed")
    if final.exists() or failure.exists():
        raise CompositionError("That production job already exists. Use a new job ID.")
    staging=Path(tempfile.mkdtemp(prefix="."+job.job_id+"-",dir=output_root))
    result=OverlayResult(job.job_id)
    result.copied_source_pages=0
    result.rendered_inserted_blanks=0
    current=None
    renderer=None
    chunk=layers=None
    plan=None
    result.source_pages=spec.source.pages
    result.warnings.extend(spec.source.warnings)
    if any(obj.profile and obj.profile.validation=="pending" for obj in spec.objects):
        result.warnings.append("Barcode profile: machine validation pending. Software decoding does not certify inserter compatibility.")
    try:
        check_cancel(is_cancelled)
        plan=overlay_plan(spec,is_cancelled=is_cancelled)
        result.excluded_source_pages=plan.excluded_pages
        result.source_pages=plan.source_pages
        result.input_envelopes=plan.envelopes
        result.expected_pages=plan.output_pages
        result.inserted_blanks=plan.inserted_blanks
        result.sheets=plan.sheets
        if isinstance(plan,PrintPlan):
            from composition.media.ticket import export_print_package
            result.media_summary=export_print_package(staging,plan,"production.pdf",is_cancelled=is_cancelled,write_ticket=not _defer_media_ticket)
            result.media_summary["inserted_blanks"]=plan.inserted_blanks
            result.warnings.append("Printer media profile: device validation pending. Inspect selection settings and proof print before production.")
        if progress:
            progress(0,plan.output_pages,"Creating hash-checked source snapshot")
        snapshot=snapshot_source(spec.source.path,staging/"source-snapshot.pdf",spec.source.sha256,is_cancelled=is_cancelled)
        verified=inspect_source(snapshot,spec.settings,is_cancelled=is_cancelled,progress=progress,
                                uniform=spec.source.geometry_mode == "uniform")
        if verified.pages != spec.source.pages or verified.geometries != spec.source.geometries:
            raise CompositionError("Inspected source page count/geometry does not match the saved project. Reinspect the source.")
        executable=qpdf_executable()
        assets=[path for obj in spec.objects for path in
                (obj.element.image,obj.element.font.file,
                 *(font.file for font in obj.element.glyph_repairs.values()),
                 obj.element.rules.alternative.image if obj.element.rules.alternative else "") if path]
        asset_hashes={path:file_hash(Path(path)) for path in assets}
        with ExitStack() as resources:
            source=resources.enter_context(fitz.open(snapshot))
            renderer=resources.enter_context(OverlayRenderer(spec,auto_repair=job.auto_repair,
                       fallback_directory=staging/"fallback",is_cancelled=is_cancelled))
            try:
                renderer.renderer.prepare_fonts(page_records(spec,plan,job.job_id,is_cancelled,external_values),staging/"fonts",
                            progress,is_cancelled,audit_path=staging/"glyph-repairs.csv")
            finally:
                result.font_scan=dict(renderer.renderer.repair_summary)
            # Validate scopes, all payloads, required read positions and page boundaries before composition.
            marks_file=resources.enter_context((staging/"marks.jsonl").open("w",encoding="utf-8"))
            for page in plan.pages():
                check_cancel(is_cancelled)
                current=page
                fields=page_values(spec,page,job.job_id,external_values)
                selected=renderer.selections(fields,verified.page_geometry(page))
                result.expected_barcodes+=sum(element.type in ("qr","code128","i25") for element,_obj,_value in selected)
            current=None
            pages_file=resources.enter_context((staging/"pages.csv").open("w",encoding="utf-8-sig",newline=""))
            envelopes_file=resources.enter_context((staging/"envelopes.csv").open("w",encoding="utf-8-sig",newline=""))
            pages_writer,env_writer=csv.writer(pages_file),csv.writer(envelopes_file)
            row(pages_writer,["Source page","Output page","Envelope sequence","Letter page","Print page","Sheet no","Side","Inserted blank", "Original PDF page"])
            row(env_writer,["Envelope index","Envelope sequence","Source start","Source end","Output start","Output end","Source pages","Output pages","Sheets","Status"])
            chunks=[]
            pending = iter(plan.pages())
            per_envelope = plan.settings_for(1).output_pages_per_envelope
            batch_size = job.chunk_size if spec.settings.groups else ((job.chunk_size + per_envelope-1)//per_envelope)*per_envelope
            while batch := list(islice(pending, batch_size)):
                chunk, layers = fitz.open(), fitz.open()
                prepared = []
                for page in batch:
                    check_cancel(is_cancelled)
                    current = page
                    fields = page_values(spec, page, job.job_id,external_values)
                    geom = verified.page_geometry(page)
                    layer_index, marks = renderer.build_layer(layers, page, fields, geom)
                    prepared.append((page, fields, geom, layer_index, marks))
                # Freeze layer resources before copying them into the output chunk.
                for page, fields, geom, layer_index, marks in prepared:
                    check_cancel(is_cancelled)
                    current = page
                    renderer.stamp(chunk, layers, layer_index, source, page, geom)
                    result.copied_source_pages += int(page.source_page is not None)
                    result.rendered_inserted_blanks += int(page.source_page is None)
                    result.rendered_barcodes += len(marks)
                    for mark in marks:
                        marks_file.write(json.dumps(mark, ensure_ascii=False)+"\n")
                    row(pages_writer, [page.source_page or "", page.output_page, fields["EnvelopeSeq"], fields["LetterPage"],
                                       page.print_page, fields["SheetNo"], fields["Side"], fields["IsInsertedBlank"],
                                       spec.source_link["page_map"][page.source_page-1]+1
                                       if page.source_page and spec.source_link else page.source_page or ""])
                    if page.print_page == page.settings.output_pages_per_envelope:
                        result.processed_envelopes += 1
                        result.composed_envelopes += 1
                        row(env_writer, plan.envelope_row(page.envelope, "Composed; final QC pending"))
                    if progress and (page.output_page % 25 == 0 or page.output_page == plan.output_pages):
                        progress(page.output_page, plan.output_pages,
                                 f"Overlay envelope {page.envelope:,}/{plan.envelopes:,}; page {page.output_page:,}")
                check_cancel(is_cancelled)
                path = staging/f"chunk-{len(chunks):06}.pdf"
                chunk.save(path, deflate=True, garbage=1)
                result.generated_pages += chunk.page_count
                chunk.close()
                layers.close()
                chunk = layers = None
                chunks.append(path)
                prepared.clear()

        current=None
        check_cancel(is_cancelled)
        if progress:
            progress(plan.output_pages,plan.output_pages,"Assembling and validating overlay PDF")
        pdf=staging/"production.pdf"
        result.assembler_peak_memory_bytes=_assemble(chunks,pdf,executable,is_cancelled)
        validate_pdf_file(pdf,expected_page_count=plan.output_pages)
        for path in chunks:
            path.unlink()
        with fitz.open(pdf) as document, (staging/"marks.jsonl").open(encoding="utf-8") as marks:
            result.generated_pages=document.page_count
            with (staging/"barcodes.csv").open("w",encoding="utf-8-sig",newline="") as stream, (staging/"barcodes.jsonl").open("w",encoding="utf-8") as audit:
                qc_envelope=None
                writer=csv.writer(stream)
                row(writer,["Output page","Source page","Envelope","Object","Symbology","Profile","Payload","QC",
                            "Sheet", "Group sequence", "Inserts 1-3", "Inserts 4-6", "EOG", "Check digit"])
                for raw in marks:
                    check_cancel(is_cancelled)
                    mark=json.loads(raw)
                    current=plan.output_page(mark["output_page"])
                    if qc_envelope is not None and qc_envelope != mark["envelope"]:
                        result.successful_envelopes+=1
                    qc_envelope=mark["envelope"]
                    check_mark(document[mark["output_page"]-1],mark)
                    result.decoded_barcodes+=1
                    audit.write(json.dumps({**mark,"qc":"decoded_exact"},ensure_ascii=False)+"\n")
                    parts = mark.get("parts", {})
                    row(writer,[mark["output_page"],mark["source_page"] or "",mark["envelope"],mark["object"],
                                mark["symbology"],mark["profile"],mark["payload"],"Decoded: exact match", mark.get("sheet", ""),
                                parts.get("group", ""), parts.get("inserts_1_3", ""), parts.get("inserts_4_6", ""), parts.get("eog", ""), parts.get("check_digit", "")])
                    if progress and result.decoded_barcodes%100==0:
                        progress(result.decoded_barcodes,result.expected_barcodes,f"Barcode QC {result.decoded_barcodes:,}/{result.expected_barcodes:,}")
                # The assembled PDF has passed output validation and all existing marks
                # have decoded. Envelopes without marks are valid too; barcode presence
                # is required only for projects declaring a machine control object.
                result.successful_envelopes=plan.envelopes
        current=None
        if any(file_hash(Path(path))!=digest for path,digest in asset_hashes.items()):
            raise CompositionError("An overlay image or font changed during production. Review and run again.")
        result.unverified_envelopes=plan.envelopes-result.successful_envelopes
        result.generated_files=1
        reconcile(result)
        if isinstance(plan,PrintPlan) and not _defer_media_ticket:
            from composition.media.postscript import export_postscript
            ps=export_postscript(staging,spec.media,pdf.name,is_cancelled=is_cancelled,progress=progress)
            result.media_summary.update(ps)
            if ps:
                result.output_ps=str(final/ps["postscript"])
        result.output_size=pdf.stat().st_size
        result.output_pdf=str(final/pdf.name)
        result.report_dir=str(final)
        result.composer_peak_memory_bytes=peak_memory()
        # Replace the composed/pending envelope table only after complete final QC.
        with (staging/"envelopes.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.writer(stream)
            row(writer,["Envelope index","Envelope sequence","Source start","Source end","Output start","Output end","Source pages","Output pages","Sheets","Status"])
            for envelope in range(1,plan.envelopes+1):
                row(writer, plan.envelope_row(envelope, "Completed"))
        result.status="completed"
        result.finished_at=now()
        if additional_reports:
            additional_reports(staging,result)
        write_summary(staging,result,spec)
        for path in (staging/"source-snapshot.pdf",staging/"marks.jsonl"):
            path.unlink()
        for directory in (staging/"fonts",staging/"fallback"):
            if directory.exists():
                if not directory.resolve().is_relative_to(staging.resolve()):
                    raise CompositionError("Unsafe overlay asset cleanup path.")
                shutil.rmtree(directory)
        check_cancel(is_cancelled)
        os.rename(staging,final)
        return result
    except Exception as exc:
        for document in (chunk,layers):
            if document is not None:
                document.close()
        result.status="cancelled" if isinstance(exc,JobCancelled) or (is_cancelled and is_cancelled()) else "failed"
        result.error=str(exc)
        if current is not None and result.status=="failed":
            _error_page(result,current)
            result.failed_envelopes=1
            result.processed_envelopes=max(result.processed_envelopes,current.envelope)
            result.successful_envelopes=min(result.successful_envelopes,result.processed_envelopes-1)
        elif plan is not None and getattr(exc,"record_ordinal",None):
            index=exc.record_ordinal
            page=plan.output_page(index)
            _error_page(result,page)
            if result.status == "failed":
                result.failed_envelopes = 1
        result.unverified_envelopes=max(0,result.input_envelopes-result.successful_envelopes-result.failed_envelopes)
        result.output_pdf=""
        result.output_ps=""
        result.generated_files=0
        result.finished_at=now()
        result.report_dir=str(failure)
        for path in staging.glob("*.pdf"):
            path.unlink(missing_ok=True)
        from composition.media.postscript import discard_postscript
        discard_postscript(staging,result.media_summary)
        (staging/"default_ticket.jdf").unlink(missing_ok=True)
        for directory in (staging/"fonts",staging/"fallback"):
            if directory.exists():
                if not directory.resolve().is_relative_to(staging.resolve()):
                    raise CompositionError("Unsafe overlay asset cleanup path.") from None
                shutil.rmtree(directory)
        try:
            write_summary(staging,result,spec)
            os.rename(staging,failure)
        except OSError as report_error:
            result.report_dir=""
            result.warnings.append(f"Unable to publish diagnostic reports: {report_error}")
        return result
    finally:
        if staging.exists():
            if staging.resolve().parent!=output_root or not staging.name.startswith("."+job.job_id+"-"):
                raise CompositionError("Unsafe staging cleanup path.")
            shutil.rmtree(staging)
