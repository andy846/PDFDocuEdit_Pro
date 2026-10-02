from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import asdict

import fitz
import pytest

from composition.overlay.model import BarcodeProfile, BarcodeToken, EnvelopeSpec, OverlayObject
from composition.overlay.serializer import load_project, save_project
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.planner import EnvelopePlan
from composition.pdf_source.source import inspect_source, snapshot_source
from composition.template.model import CompositionError, Element


def make_source(path, pages=6, rotation=0, crop=False):
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page(width=595,height=842)
            page.insert_text((100,230), f"Original Source Page {index+1}")
            if crop:
                page.set_cropbox(fitz.Rect(20,30,575,812))
            page.set_rotation(rotation)
        doc.save(path)
    return path


def sample_spec(tmp_path, pages=6, duplex=False):
    cfg = EnvelopeSettings(duplex=duplex)
    path = make_source(tmp_path / "source.pdf",pages)
    return EnvelopeSpec(inspect_source(path,cfg),cfg,[
        OverlayObject(Element(value="{{EnvelopeSeq}}",x_mm=20,y_mm=20)),
        OverlayObject(Element(type="code128",x_mm=20,y_mm=35,width_mm=90,height_mm=14),
                      control=True,profile=BarcodeProfile())])


@pytest.mark.parametrize("duplex,total,sheets,blanks",[(False,3000,3000,0),(True,4000,2000,1000)])
def test_3000_page_lazy_group_and_sheet_mapping(duplex,total,sheets,blanks):
    plan=EnvelopePlan(3000,EnvelopeSettings(duplex=duplex))
    assert (plan.envelopes,plan.output_pages,plan.sheets,plan.inserted_blanks)==(1000,total,sheets,blanks)
    assert plan.page(1000,3).fields()["EnvelopeSeq"]=="001000"
    assert plan.page(1000,3).source_page==3000
    if duplex:
        page=plan.page(1000,4)
        assert page.source_page is None and page.output_page==4000
        assert page.fields()["Side"]=="Back" and page.fields()["SheetNo"]=="2"
    else:
        assert plan.page(2,1).output_page==4
    assert len(list(plan.pages()))==total


@pytest.mark.parametrize("pages",[0,1,3001])
def test_incomplete_groups_are_not_silently_discarded(pages):
    with pytest.raises(CompositionError):
        EnvelopePlan(pages,EnvelopeSettings())


def test_custom_sequence_and_overflow():
    plan=EnvelopePlan(6,EnvelopeSettings(start=500,increment=7,digits=4,prefix="ENV-"))
    assert plan.page(2,1).fields()["EnvelopeSeq"]=="ENV-0507"
    with pytest.raises(CompositionError,match="exceeds"):
        EnvelopePlan(6,EnvelopeSettings(start=999999))


def test_tokens_are_declarative_and_width_checked():
    fields=EnvelopePlan(6,EnvelopeSettings()).page(2,3).fields()
    assert BarcodeProfile().payload(fields)=="0000020303"
    profile=BarcodeProfile(tokens=[BarcodeToken("literal","J-"),BarcodeToken(value="SheetNo",width=2)])
    profile.validate()
    assert profile.payload(fields)=="J-03"
    profile.tokens[1].value="__import__('os')"
    with pytest.raises(CompositionError,match="Unknown barcode field"):
        profile.validate()
    with pytest.raises(CompositionError,match="cannot fit"):
        BarcodeProfile(tokens=[BarcodeToken(value="SourcePage",width=1)]).payload({"SourcePage":"10"})


def test_save_restore_and_version(tmp_path):
    spec=sample_spec(tmp_path)
    raw=spec.to_dict()
    assert EnvelopeSpec.from_dict(raw).to_dict()==raw
    target=save_project(spec,tmp_path / "job.pdcx")
    assert load_project(target).to_dict()==raw
    raw["overlay_version"]=4
    with pytest.raises(CompositionError,match="version"):
        EnvelopeSpec.from_dict(raw)
    spec.source.path=str(tmp_path / "missing.pdf")
    target=save_project(spec,target)
    assert load_project(target).source.path==spec.source.path


def test_snapshot_source_change_cancel_and_existing_target(tmp_path):
    spec=sample_spec(tmp_path)
    source=spec.source.path
    copied=tmp_path / "snapshot.pdf"
    snapshot_source(source,copied,spec.source.sha256)
    assert hashlib.sha256(copied.read_bytes()).hexdigest()==spec.source.sha256
    with pytest.raises(FileExistsError):
        snapshot_source(source,copied,spec.source.sha256)
    assert copied.exists(),"An existing snapshot must not be deleted"
    with pytest.raises(CompositionError,match="cancel"):
        snapshot_source(source,tmp_path / "cancel.pdf",spec.source.sha256,is_cancelled=lambda:True)
    assert not (tmp_path / "cancel.pdf").exists()
    make_source(source,9)
    with pytest.raises(CompositionError,match="changed since preview"):
        snapshot_source(source,tmp_path / "changed.pdf",spec.source.sha256)
    assert not (tmp_path / "changed.pdf").exists()


def test_role_geometry_and_forms_need_review(tmp_path):
    path=make_source(tmp_path/"different.pdf")
    with fitz.open(path) as doc:
        doc[3].set_rotation(90)
        doc.saveIncr()
    with pytest.raises(CompositionError,match="Source page 4.*geometry"):
        inspect_source(path,EnvelopeSettings())
    form=make_source(tmp_path/"form.pdf")
    with fitz.open(form) as doc:
        widget=fitz.Widget()
        widget.field_name="Name"
        widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect=fitz.Rect(20,20,200,50)
        doc[0].add_widget(widget)
        doc.saveIncr()
    with pytest.raises(CompositionError,match="interactive forms"):
        inspect_source(form,EnvelopeSettings())


def test_headless_source_and_models_do_not_import_qt():
    script="import sys; import composition.pdf_source.source, composition.overlay.model; assert not any(n.startswith('PyQt') for n in sys.modules)"
    subprocess.run([sys.executable,"-c",script],check=True)


def test_unknown_fields_and_wrong_scope_are_rejected(tmp_path):
    spec=sample_spec(tmp_path)
    spec.objects[0].element.value="{{Customer_Name}}"
    with pytest.raises(CompositionError,match="Unknown overlay fields"):
        spec.validate()
    spec.objects[0].element.value="{{EnvelopeSeq}}"
    spec.objects[0].scope="exec"
    with pytest.raises(CompositionError,match="scope"):
        spec.validate()
    raw=asdict(spec)
    raw["settings"]["duplex"]=1
    with pytest.raises(CompositionError,match="Duplex"):
        EnvelopeSpec.from_dict(raw)
