from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

import fitz
import pytest
from PyQt6.QtWidgets import QApplication

from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.generator import generate, reconcile
from composition.overlay.model import BarcodeProfile, EnvelopeSpec, OverlayJob, OverlayObject
from composition.overlay.renderer import render_preview
from composition.overlay.serializer import load_project, save_project
from composition.pdf_source.detection import DetectionConfig, detect_texts, edit_boundary, page_text, scan_pdf
from composition.pdf_source.model import EnvelopeSettings, SourceInfo
from composition.pdf_source.planner import EnvelopePlan
from composition.pdf_source.source import inspect_source
from composition.template.model import MM_TO_PT, CompositionError, Element
from composition.worker import dispatch
from tests.composition.test_pdf_overlay_ui import finish


def make_pdf(tmp_path, texts, name="source.pdf"):
    path = tmp_path/name
    with fitz.open() as pdf:
        for text in texts:
            page = pdf.new_page(width=595, height=842)
            page.insert_text((70, 200), text)
        pdf.save(path)
    return path


def variable_spec(tmp_path, lengths=(3, 1, 7, 2), duplex=False):
    texts = [f"Page {n} of {count}\nAccount No: {index:06}" for index, count in enumerate(lengths, 1) for n in range(1,count+1)]
    result = scan_pdf(make_pdf(tmp_path,texts), DetectionConfig())
    review = result["detection"]
    review["accepted"] = True
    settings = EnvelopeSettings(pages_per_envelope=1, duplex=duplex, groups=review["groups"])
    return EnvelopeSpec(SourceInfo(**result["source"]), settings, [
        OverlayObject(Element(value="{{EnvelopeSeq}} / {{LetterPage}} / {{LetterPageCount}}")),
        OverlayObject(Element(type="code128", x_mm=20, y_mm=35, width_mm=90, height_mm=14), control=True, profile=BarcodeProfile())
    ], detection_review=review)


def test_variable_page_number_groups_and_integrity_qc():
    report = detect_texts(["Page 1 of 3", "Page 2 of 3", "Page 3 of 3", "Page 1 of 1", "Page 1 of 2", "Page 2 of 2"], DetectionConfig())
    assert report["groups"] == [[1,3],[4,4],[5,6]] and not report["findings"]
    broken = detect_texts(["Page 1 of 4", "Page 2 of 4", "Page 4 of 4", "Page 1 of 2"], DetectionConfig())
    assert any(f["code"] == "page_sequence" and "Expected printed page 3" in f["message"] for f in broken["findings"])
    assert any(f["code"] == "incomplete_sequence" for f in broken["findings"])
    missing = detect_texts(["unmarked", "Page 1 of 1\nPage 2 of 2"], DetectionConfig())
    assert {f["code"] for f in missing["findings"]} >= {"missing_signal", "ambiguous_signal"}


def test_id_changes_missing_id_and_contiguous_identity():
    cfg = DetectionConfig(rules=[{"kind":"document_id","pattern":"Member No: {ID}"}])
    result = detect_texts(["Member No: 000001", "Member No: 000001", "Member No: 000002", "continuation", "Member No: 000002"],cfg)
    assert result["groups"] == [[1,2],[3,5]]
    assert result["findings"][0]["page"] == 4
    assert all("000001" not in f["message"] for f in result["findings"])


@pytest.mark.parametrize("combine,groups", [("any",[[1,2],[3,3],[4,4]]),("all",[[1,2],[3,4]])])
def test_structured_combination_and_conflicting_evidence(combine,groups):
    cfg=DetectionConfig(rules=[{"kind":"document_id","pattern":"Account: {ID}"}, {"kind":"first_text","terms":["START"]}],combine=combine)
    result=detect_texts(["Account: A\nSTART","Account: A","Account: B\nSTART","Account: B\nSTART"],cfg)
    assert result["groups"] == groups
    assert result["findings"][-1]["code"] == "rule_disagreement"
    assert "confidence" not in result


@pytest.mark.parametrize("remove,groups,excluded",[(True,[[2,3],[5,5]],[1,4,6]),(False,[[1,1],[2,4],[5,6]],[])])
def test_separator_pages_retained_or_explicitly_excluded(remove,groups,excluded):
    cfg=DetectionConfig(rules=[{"kind":"separator","terms":["SEPARATOR"]}],remove_separators=remove)
    result=detect_texts(["SEPARATOR","A","A2","SEPARATOR","B","SEPARATOR"],cfg)
    assert result["groups"] == groups and result["excluded_pages"] == excluded


def test_first_markers_all_terms_and_region_presence():
    cfg=DetectionConfig(rules=[{"kind":"first_text","terms":["Statement Date","Account Number"]}])
    assert detect_texts(["Statement Date\nAccount Number","Account Number","Statement Date\nAccount Number"],cfg)["groups"] == [[1,2],[3,3]]
    cfg=DetectionConfig(rules=[{"kind":"region_present"}],region_mm=[20,20,80,30])
    assert detect_texts(["address","","next address"],cfg)["groups"] == [[1,2],[3,3]]


@pytest.mark.parametrize("rules",[[{"kind":"page_number","pattern":".*"}], [{"kind":"document_id","pattern":"{ID}"}], [{"kind":"python","value":"eval"}], [{"kind":"first_text","terms":[]}], [{"kind":"region_present"}]])
def test_detection_untrusted_invalid_rules_rejected(rules):
    with pytest.raises(CompositionError):
        DetectionConfig(rules=rules).validate()


def test_region_pdf_coordinates_and_cancellation_source_identity(tmp_path):
    path=make_pdf(tmp_path,["Page 1 of 1\nAccount No: A"])
    with fitz.open(path) as pdf:
        span=pdf[0].search_for("Page 1 of 1")[0]
        rect=fitz.Rect(span.x0-1,span.y0-1,span.x1+1,span.y1+1)
        assert "Page 1 of 1" in page_text(pdf[0],[rect.x0/MM_TO_PT,rect.y0/MM_TO_PT,rect.width/MM_TO_PT,rect.height/MM_TO_PT])
        pdf[0].set_rotation(90)
        rotated=rect*pdf[0].rotation_matrix
        assert "Page 1 of 1" in page_text(pdf[0],[rotated.x0/MM_TO_PT,rotated.y0/MM_TO_PT,rotated.width/MM_TO_PT,rotated.height/MM_TO_PT])
    with pytest.raises(CompositionError,match="changed"):
        scan_pdf(path,DetectionConfig(),expected_sha256="0"*64)
    with pytest.raises(CompositionError,match="cancel"):
        scan_pdf(path,DetectionConfig(),is_cancelled=lambda:True)


def test_boundary_review_split_merge_and_schema_save_restore(tmp_path):
    spec=variable_spec(tmp_path)
    value=spec.to_dict()
    value["detection_review"]["accepted"]=False
    with pytest.raises(CompositionError,match="Review"):
        EnvelopeSpec.from_dict(value)
    changed=edit_boundary(spec.detection_review,0,split_page=2)
    assert changed["groups"][:2]==[[1,1],[2,3]] and not changed["accepted"]
    merged=edit_boundary(changed,1,merge_previous=True)
    assert merged["groups"]==spec.settings.groups and len(merged["edits"])==2
    assert spec.detection_review["edits"]==[]
    target=save_project(spec,tmp_path/"detected.pdcx")
    assert load_project(target).to_dict()==spec.to_dict()
    value=spec.to_dict()
    value["overlay_version"]=2
    with pytest.raises(CompositionError,match="version 3"):
        EnvelopeSpec.from_dict(value)


def test_dynamic_duplex_mapping_source_coverage_and_lookup():
    cfg=EnvelopeSettings(groups=[[1,3],[4,4],[5,11],[12,13]],duplex=True)
    plan=EnvelopePlan(13,cfg)
    assert (plan.envelopes,plan.output_pages,plan.inserted_blanks,plan.sheets)==(4,16,3,8)
    assert plan.page(3,7).source_page==11
    assert plan.page(3,8).fields()["IsInsertedBlank"]=="1"
    assert plan.page(3,8).fields()["LetterPageCount"]=="7"
    assert plan.output_page(15)==plan.page(4,1)
    assert plan.page(4,2).fields()["SheetCount"]=="1"
    with pytest.raises(CompositionError,match="overlap, omit"):
        EnvelopePlan(5,EnvelopeSettings(groups=[[1,2],[4,5]]))
    with pytest.raises(CompositionError):
        EnvelopePlan(5,EnvelopeSettings(groups=[[1,3],[4,5]],excluded_pages=[2]))


@pytest.mark.parametrize("duplex",[False,True])
def test_actual_production_variable_groups_barcodes_reconcile_preview_and_reports(tmp_path,duplex):
    spec=variable_spec(tmp_path,duplex=duplex)
    result=generate(OverlayJob(spec.to_dict(),str(tmp_path/"output"),chunk_size=3))
    assert result.status=="completed",result.error
    assert result.source_pages==result.copied_source_pages==13
    assert result.input_envelopes==result.successful_envelopes==4
    assert result.expected_barcodes==result.decoded_barcodes==13
    assert result.generated_pages==(16 if duplex else 13)
    reconcile(result)
    preview,_fields=render_preview(spec,3,7)
    plan=EnvelopePlan(13,spec.settings)
    with fitz.open(stream=preview,filetype="pdf") as single,fitz.open(result.output_pdf) as final:
        assert single[0].get_pixmap().samples==final[plan.page(3,7).output_page-1].get_pixmap().samples
    with (Path(result.report_dir)/"envelopes.csv").open(encoding="utf-8-sig") as stream:
        rows=list(csv.DictReader(stream))
    assert [int(r["Source pages"]) for r in rows]==[3,1,7,2]
    assert all(r["Status"]=="Completed" for r in rows)
    assert (Path(result.report_dir)/"detection.csv").exists()
    audit=json.loads((Path(result.report_dir)/"job.json").read_text(encoding="utf-8"))
    assert audit["detection_review"]["accepted"] is True


def test_separator_exclusion_production_reconciles_without_source_loss(tmp_path):
    config=DetectionConfig(rules=[{"kind":"separator","terms":["SEPARATOR"]}])
    value=scan_pdf(make_pdf(tmp_path,["A","A2","SEPARATOR","B","SEPARATOR"]),config)
    report=value["detection"]
    report["accepted"]=True
    spec=EnvelopeSpec(SourceInfo(**value["source"]),EnvelopeSettings(groups=report["groups"],excluded_pages=report["excluded_pages"],duplex=True),
                      [OverlayObject(Element(value="{{EnvelopeSeq}}"))],detection_review=report)
    result=generate(OverlayJob(spec.to_dict(),str(tmp_path/"output"),chunk_size=2))
    assert result.status=="completed",result.error
    assert (result.source_pages,result.excluded_source_pages,result.copied_source_pages,result.inserted_blanks,result.generated_pages)==(5,2,3,1,4)
    with fitz.open(result.output_pdf) as pdf:
        assert "SEPARATOR" not in "".join(p.get_text() for p in pdf)
    result.excluded_source_pages=1
    with pytest.raises(CompositionError,match="RECONCILIATION"):
        reconcile(result)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_ui_review_apply_undo_dynamic_navigation_and_changes_require_rescan(app,tmp_path,monkeypatch):
    monkeypatch.setattr(OverlayWindow,"load_fonts",lambda self:None)
    monkeypatch.setattr(OverlayWindow,"render_preview",lambda self:None)
    window=OverlayWindow()
    try:
        spec=variable_spec(tmp_path)
        window.apply_spec(spec.to_dict())
        window.show()
        requests=[]
        monkeypatch.setattr(window,"worker",lambda request,*args,**kwargs:requests.append(request))
        dialog=MailpieceDialog(window)
        dialog.show()
        assert dialog.model.rowCount()==4 and not dialog.apply_button.isEnabled()
        dialog.acknowledge.setChecked(True)
        assert dialog.apply_button.isEnabled()
        dialog.report=edit_boundary(dialog.report,0,split_page=2)
        dialog.show_report()
        dialog.acknowledge.setChecked(True)
        dialog.apply()
        assert window.spec.settings.groups[:2]==[[1,1],[2,3]]
        assert window.undo.count()==1
        window.undo.undo()
        assert window.spec.settings.groups==spec.settings.groups
        window.envelope.setValue(2)
        assert window.print_page.maximum()==1
        window.envelope.setValue(3)
        assert window.print_page.maximum()==7
        dialog=MailpieceDialog(window)
        dialog.show()
        dialog.number_pattern.setText("{CURRENT}/{TOTAL}")
        assert dialog.report is None and not dialog.apply_button.isEnabled()
        dialog.reject()
    finally:
        finish(window)


def test_worker_scan_transport_and_source_preview(tmp_path):
    path=make_pdf(tmp_path,["Page 1 of 1","Page 1 of 2","Page 2 of 2"])
    value=dispatch({"task":"mailpiece_scan","source":str(path),"config":asdict(DetectionConfig())})
    assert value["detection"]["groups"]==[[1,1],[2,3]]
    source=value["source"]
    preview=dispatch({"task":"mailpiece_preview","source":str(path),"page":2,"target":str(tmp_path/"preview.png"),"size":source["size"],"mtime_ns":source["mtime_ns"]})
    assert Path(preview["image"]).exists()




def test_first_page_only_id_mode_carries_forward_and_warns_reappearance():
    config=DetectionConfig(rules=[{"kind":"document_id","pattern":"Member: {ID}","allow_missing_continuation":True}])
    report=detect_texts(["Member: A","continuation","Member: A","continuation","Member: B","Member: A"],config)
    assert report["groups"]==[[1,4],[5,5],[6,6]]
    assert [f["code"] for f in report["findings"]]==["repeated_id"]


def test_background_scan_review_responsiveness_and_atomic_apply(app,tmp_path,monkeypatch):
    from PyQt6.QtCore import QTimer

    from tests.composition.test_workspace import wait_until
    monkeypatch.setattr(OverlayWindow,"load_fonts",lambda self:None)
    monkeypatch.setattr(OverlayWindow,"render_preview",lambda self:None)
    window=OverlayWindow()
    timer=QTimer()
    ticks=[]
    timer.timeout.connect(lambda:ticks.append(1))
    timer.start(10)
    try:
        texts=["Page 1 of 1","Page 1 of 2","Page 2 of 2"]
        path=make_pdf(tmp_path,texts)
        cfg=EnvelopeSettings(pages_per_envelope=1)
        window.apply_spec(EnvelopeSpec(inspect_source(path,cfg),cfg,[OverlayObject(Element(value="{{EnvelopeSeq}}"))]).to_dict())
        window.show()
        before=window.spec.to_dict()
        window.detect_mailpieces()
        dialog=window.detection_dialog
        dialog.scan()
        wait_until(lambda:dialog.report is not None and not dialog.scan_worker and not window.active_worker)
        assert ticks and dialog.report["groups"]==[[1,1],[2,3]]
        assert window.spec.to_dict()==before and not dialog.apply_button.isEnabled()
        dialog.acknowledge.setChecked(True)
        dialog.apply()
        assert window.spec.settings.groups==[[1,1],[2,3]] and window.undo.count()==1
        window.undo.undo()
        assert window.spec.to_dict()==before
    finally:
        timer.stop()
        finish(window)


def test_malformed_review_metadata_is_rejected(tmp_path):
    spec=variable_spec(tmp_path)
    value=spec.to_dict()
    value["detection_review"]["findings"]=[{"page":0,"message":"bad"}]
    with pytest.raises(CompositionError,match="finding"):
        EnvelopeSpec.from_dict(value)


def test_pending_detection_project_cannot_silently_generate_fixed_groups(tmp_path):
    path=make_pdf(tmp_path,["Page 1 of 2","Page 2 of 2"])
    cfg=EnvelopeSettings(pages_per_envelope=1)
    spec=EnvelopeSpec(inspect_source(path,cfg,uniform=True),cfg,detection_review={"required":True,"accepted":False})
    assert spec.needs_detection_review
    with pytest.raises(CompositionError,match="review and accept"):
        generate(OverlayJob(spec.to_dict(),str(tmp_path/"output")))
    assert not (tmp_path/"output").exists()


def test_review_narrow_window_controls_and_drag_search_region(app,tmp_path,monkeypatch):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QScrollArea
    monkeypatch.setattr(OverlayWindow,"load_fonts",lambda self:None)
    monkeypatch.setattr(OverlayWindow,"render_preview",lambda self:None)
    window=OverlayWindow()
    try:
        spec=variable_spec(tmp_path)
        window.apply_spec(spec.to_dict())
        def worker(request,ready,failed=None,**kwargs):
            if request["task"]=="mailpiece_preview":
                ready(dispatch(request))
            return None
        monkeypatch.setattr(window,"worker",worker)
        dialog=MailpieceDialog(window)
        dialog.show()
        dialog.resize(960,640)
        dialog.show_source_page(1)
        app.processEvents()
        assert dialog.apply_button.mapTo(dialog,dialog.apply_button.rect().topRight()).x()<960
        assert all(scroll.horizontalScrollBar().maximum()==0 for scroll in dialog.findChildren(QScrollArea))
        assert dialog.number_pattern.isVisible() and dialog.id_pattern.isHidden()
        start=dialog.preview.mapFromScene(QPointF(80,130))
        end=dialog.preview.mapFromScene(QPointF(120,160))
        QTest.mousePress(dialog.preview.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(dialog.preview.viewport(),end)
        QTest.mouseRelease(dialog.preview.viewport(),Qt.MouseButton.LeftButton,pos=end)
        assert not dialog.whole.isChecked()
        assert dialog.region[2].value()==pytest.approx(40,abs=4)
        assert dialog.region[3].value()==pytest.approx(30,abs=4)
        assert dialog.report is None and not dialog.apply_button.isEnabled()
        dialog.reject()
    finally:
        finish(window)


def test_reinspect_changed_page_count_requires_detection_and_keeps_objects(app,tmp_path,monkeypatch):
    monkeypatch.setattr(OverlayWindow,"load_fonts",lambda self:None)
    monkeypatch.setattr(OverlayWindow,"render_preview",lambda self:None)
    window=OverlayWindow()
    try:
        spec=variable_spec(tmp_path)
        spec.objects[0].scope="letter_page"
        spec.objects[0].letter_page=3
        window.apply_spec(spec.to_dict())
        before=window.spec.to_dict()["objects"]
        path=make_pdf(tmp_path,["Page 1 of 4","Page 2 of 4","Page 3 of 4","Page 4 of 4"])
        def worker(request,ready,failed=None,**kwargs):
            if request["task"]=="overlay_inspect":
                ready(dispatch(request))
            return None
        monkeypatch.setattr(window,"worker",worker)
        window.inspect_source(path,spec.settings,preserve=True)
        assert window.spec.source.pages==4 and window.spec.source.sha256!=spec.source.sha256
        assert window.spec.settings.groups==[] and window.spec.needs_detection_review
        assert window.spec.to_dict()["objects"]==before
        assert not window.actions["generate"].isEnabled()
    finally:
        finish(window)
