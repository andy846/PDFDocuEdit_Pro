from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict

import fitz
import pytest

from composition.overlay.generator import generate, reconcile
from composition.overlay.model import BarcodeProfile, BarcodeToken, OverlayJob
from composition.overlay.renderer import render_preview
from composition.pdf_source.source import inspect_source
from composition.template.model import CompositionError
from tests.composition.test_pdf_overlay_models import make_source, sample_spec


def run_job(tmp_path, spec, chunk=4):
    return generate(OverlayJob(spec.to_dict(),str(tmp_path/"output"),chunk_size=chunk))


@pytest.mark.parametrize("duplex,pages,sheets",[(False,6,6),(True,8,4)])
def test_production_exact_pages_original_content_barcodes_and_reports(tmp_path,duplex,pages,sheets):
    spec=sample_spec(tmp_path,duplex=duplex)
    before=hashlib.sha256(open(spec.source.path,"rb").read()).hexdigest()
    result=run_job(tmp_path,spec)
    assert result.status=="completed",result.error
    assert result.generated_pages==pages and result.sheets==sheets
    assert result.successful_envelopes==result.composed_envelopes==2
    assert result.expected_barcodes==result.rendered_barcodes==result.decoded_barcodes==6
    assert result.source_pages==result.copied_source_pages==6
    assert result.rendered_inserted_blanks==result.inserted_blanks==pages-6
    assert result.font_scan["complete"] and result.unverified_envelopes==0
    reconcile(result)
    with fitz.open(spec.source.path) as source, fitz.open(result.output_pdf) as output:
        for index in range(6):
            out_index=index + index//3 if duplex else index
            assert f"Original Source Page {index+1}" in output[out_index].get_text()
            clip=fitz.Rect(0,180,595,842)
            assert source[index].get_pixmap(clip=clip).samples==output[out_index].get_pixmap(clip=clip).samples
        if duplex:
            assert output[3].get_text()=="" and output[7].get_text()==""
    assert hashlib.sha256(open(spec.source.path,"rb").read()).hexdigest()==before
    folder=__import__("pathlib").Path(result.report_dir)
    with (folder/"envelopes.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    assert len(rows)==2 and all(row["Status"]=="Completed" for row in rows)
    with (folder/"barcodes.csv").open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    assert [row["Payload"] for row in rows]==["0000010103","0000010203","0000010303","0000020103","0000020203","0000020303"]
    assert len((folder/"barcodes.jsonl").read_text().splitlines())==6
    assert "Original Source Page" not in (folder/"job.json").read_text()
    assert not (folder/"source-snapshot.pdf").exists()


@pytest.mark.parametrize("rotation",[0,90,180,270])
def test_crop_rotation_same_preview_and_output(tmp_path,rotation):
    spec=sample_spec(tmp_path)
    make_source(spec.source.path,6,rotation=rotation,crop=True)
    spec.source=inspect_source(spec.source.path,spec.settings)
    raw,_fields=render_preview(spec,2,3)
    result=run_job(tmp_path,spec)
    assert result.status=="completed",result.error
    with fitz.open(spec.source.path) as source,fitz.open(stream=raw,filetype="pdf") as preview,fitz.open(result.output_pdf) as output:
        assert source[5].rotation==output[5].rotation
        assert source[5].cropbox==output[5].cropbox and source[5].mediabox==output[5].mediabox
        assert preview[0].get_pixmap().samples==output[5].get_pixmap().samples
        assert "000002" in output[5].get_text()


def test_required_barcode_cannot_disappear_and_bounds_checked(tmp_path):
    spec=sample_spec(tmp_path)
    spec.objects[1].scope="first"
    result=run_job(tmp_path,spec)
    assert result.status=="failed" and "Required barcode" in result.error
    assert result.error_source_page==2 and not result.output_pdf
    spec.objects[1].scope="all_source"
    spec.objects[1].element.x_mm=200
    result=run_job(tmp_path,spec)
    assert result.status=="failed" and "outside" in result.error
    assert not list((tmp_path/"output").rglob("*.pdf"))


def test_duplex_front_qr_profile_and_blank_control(tmp_path):
    spec=sample_spec(tmp_path,duplex=True)
    spec.required_scope="front"
    for obj in spec.objects:
        obj.scope="front"
    barcode=spec.objects[1]
    barcode.element.type="qr"
    barcode.element.width_mm=35
    barcode.element.height_mm=35
    barcode.profile=BarcodeProfile(tokens=[BarcodeToken(),BarcodeToken(value="SheetNo",width=2),BarcodeToken(value="SheetCount",width=2)])
    result=run_job(tmp_path,spec)
    assert result.status=="completed",result.error
    assert result.expected_barcodes==result.decoded_barcodes==4
    spec.required_scope="all_output"
    barcode.scope="all_output"
    barcode.profile.tokens[1].value="PrintPage"
    barcode.profile.tokens[2].value="PrintPageCount"
    result=run_job(tmp_path,spec)
    assert result.status=="completed",result.error
    assert result.decoded_barcodes==8


@pytest.mark.parametrize("stage", ["Overlay envelope", "Assembling", "Barcode QC"])
def test_cancel_at_composition_assembly_and_qc_no_partial_output(tmp_path, stage):
    spec = sample_spec(tmp_path, pages=102 if stage == "Barcode QC" else 30)
    stopped = False
    def progress(done, total, message):
        nonlocal stopped
        if message.startswith(stage):
            stopped = True
    result = generate(OverlayJob(spec.to_dict(), str(tmp_path/"output")),
                      progress=progress, is_cancelled=lambda: stopped)
    assert result.status == "cancelled", (stage, result.error)
    assert not result.output_pdf and result.generated_files == 0
    assert not list((tmp_path/"output").rglob("*.pdf"))
    assert __import__("pathlib").Path(result.report_dir, "job.json").exists()


def test_qc_failure_and_reconciliation_mismatch_never_publish(tmp_path,monkeypatch):
    from composition.overlay import generator
    spec=sample_spec(tmp_path)
    def broken(*args):
        raise CompositionError("Intentional QC failure")
    monkeypatch.setattr(generator,"check_mark",broken)
    result=run_job(tmp_path,spec)
    assert result.status=="failed" and result.error_envelope==1
    assert result.successful_envelopes==0 and result.unverified_envelopes==1
    monkeypatch.undo()
    original=generator.reconcile
    def mismatch(result):
        result.copied_source_pages-=1
        original(result)
    monkeypatch.setattr(generator,"reconcile",mismatch)
    result=run_job(tmp_path,spec)
    assert result.status=="failed" and "RECONCILIATION" in result.error
    assert not list((tmp_path/"output").rglob("*.pdf"))


def test_changed_source_and_invalid_glyph_report(tmp_path):
    spec=sample_spec(tmp_path)
    make_source(spec.source.path,9)
    result=run_job(tmp_path,spec)
    assert result.status=="failed" and "changed since preview" in result.error
    with pytest.raises(CompositionError,match="changed since inspection"):
        render_preview(spec,1,1)
    spec=sample_spec(tmp_path)
    spec.objects[0].element.value="\u4e2d\u6587\u7530 {{EnvelopeSeq}}"
    result=run_job(tmp_path,spec)
    assert result.status=="completed",result.error
    assert result.font_scan["automatic_occurrences"]==18
    log=json.loads(__import__("pathlib").Path(result.report_dir,"job.json").read_text())
    assert log["job_type"]=="pdf_overlay"
    assert asdict(result)["source_pages"]==6


def test_saved_geometry_or_count_cannot_omit_source_pages(tmp_path):
    spec = sample_spec(tmp_path)
    spec.source.pages = 3
    result = run_job(tmp_path, spec)
    assert result.status == "failed" and "does not match" in result.error
    assert not result.output_pdf


def test_original_embedded_font_and_annotation_preserved(tmp_path):
    from composition.engine.fonts import load_font
    from composition.template.model import FontSpec
    spec = sample_spec(tmp_path)
    font, raw = load_font(FontSpec())
    with fitz.open() as document:
        for index in range(6):
            page = document.new_page(width=595, height=842)
            page.insert_font(fontname="OriginalEmbedded", fontbuffer=raw.read_bytes())
            page.insert_text((100, 230), f"Original custom font {index+1}", fontname="OriginalEmbedded")
            annotation = page.add_rect_annot(fitz.Rect(200, 250, 300, 280))
            annotation.set_colors(stroke=(1, 0, 0))
            annotation.update()
        document.save(spec.source.path)
    spec.source = inspect_source(spec.source.path, spec.settings)
    result = run_job(tmp_path, spec)
    assert result.status == "completed", result.error
    with fitz.open(spec.source.path) as source, fitz.open(result.output_pdf) as output:
        original_fonts = {hashlib.sha256(source.extract_font(f[0])[3]).hexdigest()
                          for f in source[0].get_fonts()}
        output_fonts = {hashlib.sha256(output.extract_font(f[0])[3]).hexdigest()
                        for f in output[0].get_fonts(full=True)}
        assert original_fonts <= output_fonts
        assert len(list(output[0].annots())) == 1
        clip = fitz.Rect(0, 180, 595, 842)
        assert source[0].get_pixmap(clip=clip).samples == output[0].get_pixmap(clip=clip).samples
