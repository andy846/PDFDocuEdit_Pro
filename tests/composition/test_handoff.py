"""Immutable PDF handoff, durable assets and provenance reconciliation."""
from __future__ import annotations

import copy
import csv
import shutil
from dataclasses import replace
from pathlib import Path

import fitz
import pytest

from composition.handoff import capture_pdf, validate_link
from composition.overlay.generator import generate
from composition.overlay.model import EnvelopeSpec, OverlayJob
from composition.overlay.serializer import load_project, save_project
from composition.pdf_source.model import EnvelopeSettings
from composition.template.model import CompositionError, Template
from composition.template.serializer import load_project as load_template
from composition.template.serializer import save_project as save_template
from core.pdf_engine import PdfEngine
from tests.composition.test_pdf_overlay_models import make_source


@pytest.fixture
def engine(tmp_path):
    source = make_source(tmp_path / "original.pdf", 6)
    pdf = PdfEngine()
    pdf.open(source)
    yield pdf
    pdf.close()


def capture(engine, target, **kwargs):
    return capture_pdf(engine, target, (engine.document_id, engine.revision), **kwargs)


def test_unsaved_page_edits_selected_pages_and_original_unchanged(engine, tmp_path):
    original = Path(engine.original_path).read_bytes()
    engine.rotate_pages([1, 3], 90)
    engine.delete_pages([0])
    source, link = capture(engine, tmp_path / "handoff", pages=[2, 0, 2])
    assert link["page_map"] == [0, 2]
    with fitz.open(source.path) as output:
        assert output.page_count == 2
        assert "Original Source Page 2" in output[0].get_text()
        assert output[0].rotation == 90
        assert "Original Source Page 4" in output[1].get_text()
    assert Path(engine.original_path).read_bytes() == original


def test_background_flattens_annotations_and_survives_save(engine, tmp_path):
    engine.document[2].add_text_annot((30, 30), "Note")
    source, link = capture(engine, tmp_path / "handoff", purpose="template_background", pages=[2])
    template = Template(background=source.path, source_link=link)
    saved = save_template(template, tmp_path / "template.pdcx")
    shutil.rmtree(tmp_path / "handoff")
    reopened = load_template(saved)
    assert reopened.template_version == 9
    with fitz.open(reopened.background) as pdf:
        assert "Original Source Page 3" in pdf[0].get_text()
        assert not list(pdf[0].annots() or [])
    assert reopened.source_link["page_map"] == [2]


def test_managed_overlay_saved_source_durable_and_headless_review_gate(engine, tmp_path):
    source, link = capture(engine, tmp_path / "handoff", pages=[0, 2, 4])
    spec = EnvelopeSpec(source, EnvelopeSettings(pages_per_envelope=1), source_link=link)
    with pytest.raises(CompositionError, match="Confirm grouping"):
        generate(OverlayJob(spec.to_dict(), str(tmp_path / "outputs")))
    spec.source_link["review_required"] = False
    spec.settings = replace(spec.settings, duplex=True)
    saved = save_project(spec, tmp_path / "job.pdcx")
    shutil.rmtree(tmp_path / "handoff")
    reopened = load_project(saved)
    assert reopened.overlay_version == 5
    assert reopened.source.path.startswith(str(tmp_path / "job.assets"))
    result = generate(OverlayJob(reopened.to_dict(), str(tmp_path / "outputs")))
    assert result.status == "completed", result.error
    assert result.generated_pages == 6 and result.expected_barcodes == 0
    with (Path(result.report_dir) / "pages.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["Original PDF page"] for row in rows] == ["1", "", "3", "", "5", ""]


def test_cancel_invalid_pages_and_revision_fail_without_publishing(engine, tmp_path):
    with pytest.raises(Exception, match="cancel|Cancel"):
        capture(engine, tmp_path / "cancel", is_cancelled=lambda: True)
    assert not (tmp_path / "cancel" / "source.pdf").exists()
    identity = (engine.document_id, engine.revision)
    engine.rotate_pages([0], 90)
    with pytest.raises(CompositionError, match="changed before"):
        capture_pdf(engine, tmp_path / "stale", identity)
    with pytest.raises(CompositionError, match="no longer available"):
        capture(engine, tmp_path / "bad-pages", pages=[999])


def test_legacy_formats_migrate_and_invalid_metadata_rejected(engine, tmp_path):
    source, link = capture(engine, tmp_path / "handoff")
    raw = EnvelopeSpec(source, EnvelopeSettings(pages_per_envelope=1)).to_dict()
    raw["overlay_version"] = 3
    raw.pop("source_link")
    assert EnvelopeSpec.from_dict(raw).overlay_version == 5
    value = Template().to_dict()
    value["template_version"] = 7
    value.pop("source_link")
    assert Template.from_dict(value).template_version == 9
    for mutation in ({"page_map": [0, 0]}, {"managed": "yes"}, {"page_map": [-1]}, {"version": 99}):
        broken = {**copy.deepcopy(link), **mutation}
        with pytest.raises(CompositionError):
            validate_link(broken)
    raw["overlay_version"] = 4
    raw["source_link"] = {**link, "sha256": "0"*64}
    with pytest.raises(CompositionError, match="provenance"):
        EnvelopeSpec.from_dict(raw)
