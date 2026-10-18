"""Incomplete paper settings are editable drafts, never unhandled Qt errors."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from composition.designer.sequence_controls import SequenceOperations
from composition.engine.barcode_profiles import BarcodeProfile
from composition.media.model import default_media
from composition.media.planner import build_print_plan
from composition.template.model import CompositionError, Element, PageSpec, SequenceSpec, Template


def model_for(mode="generated", profile=True):
    pages = [PageSpec(name=f"Page {i + 1}") for i in range(6)]
    if profile:
        pages[0].elements = [Element(type="i25", width_mm=100, height_mm=14,
                                     barcode_profile=BarcodeProfile.inserter().to_dict())]
    model = Template(pages=pages, record_mode=mode, generated_count=5,
                     sequences=[SequenceSpec("PageSeq", scope="page")])
    model.media = default_media()
    model.media.update(mode="template", assignments={page.id: "LH_A" for page in pages})
    return model


def imported_info():
    return {"store": "fixture.sqlite", "metadata": {"record_count": 5,
            "fields": ["Customer"], "original_fields": ["Customer"]},
            "sample": [{"Customer": "Example"}]}


@pytest.mark.parametrize("mode", ["generated", "imported"])
@pytest.mark.parametrize("profile", [False, True])
def test_incomplete_plan_preserves_record_metadata_without_inventing_samples(mode, profile):
    class Harness(SequenceOperations):
        def _config_key(self):
            return "fixture"
    window = Harness()
    window.template = model_for(mode, profile)
    messages = []
    window.message = SimpleNamespace(setText=messages.append)
    raw = imported_info() if mode == "imported" else None
    valid = window._sequence_info(raw)
    assert valid["sample"] and valid["metadata"]["record_count"] == 5
    added = PageSpec(name="Page 7")
    window.template.pages.append(added)
    with pytest.raises(CompositionError, match="logical page 7: no assigned Stock"):
        build_print_plan(window.template, 5)
    info = window._sequence_info(raw)
    assert info["metadata"] == valid["metadata"]
    assert info["store"] == valid["store"]
    assert info["sample"] == []
    assert "logical page 7" in info["sample_error"]
    assert added.id not in window.template.media["assignments"]
    assert window._sequence_info(raw) is info
    window.template.media["assignments"][added.id] = "LH_A"
    repaired = window._sequence_info(raw)
    assert not repaired.get("sample_error") and repaired["sample"]
    assert repaired["sample"][0]["PageSeq"] == "000001"


@pytest.mark.parametrize("mode", ["generated", "imported"])
def test_plus_button_keeps_incomplete_page_editable_and_undoable(qt_application, monkeypatch, mode):
    from composition.designer.workspace import CompositionWindow
    from tests.composition.test_workspace import close_window

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    window = CompositionWindow()
    try:
        model = model_for(mode)
        if mode == "imported":
            window.stores[window._config_key()] = imported_info()
        window._apply_template(model.to_dict(), page_id=model.pages[-1].id)
        window.tabs.setCurrentIndex(1)
        assert window.page_index == 5
        window.page_buttons["page_add"].click()
        assert not errors
        assert len(window.template.pages) == 7 and window.page_index == 6
        assert window.record_count == 5
        assert window.fields.count() == (2 if mode == "imported" else 1)
        assert window.sample.rowCount() == 0
        assert "no assigned Stock" in window.data_summary.text()
        assert "Paper / Tray" in window.data_summary.text()
        assert window.undo.count() == 1
        added = window.active_page_id
        assert added not in window.template.media["assignments"]
        assert window.actions["media"].isEnabled()
        # Generate remains a review entry point, never bypasses media preflight.
        assert window.actions["generate"].isEnabled()
        with pytest.raises(CompositionError, match="no assigned Stock"):
            build_print_plan(window.template, window.record_count)
        window.undo.undo()
        assert not errors and len(window.template.pages) == 6
        assert window._store()["sample"] and not window._store().get("sample_error")
        window.undo.redo()
        assert not errors and len(window.template.pages) == 7
        assert window.active_page_id == added and window._store().get("sample_error")
        before = window.template.to_dict()
        after = window.template.to_dict()
        after["media"]["assignments"][added] = "LH_A"
        window._commit(before, after, "Assign new page paper")
        assert not errors and not window._store().get("sample_error")
        assert window.sample.rowCount() > 0
        assert build_print_plan(window.template, 5).output_pages == 35
    finally:
        close_window(window)


def test_profile_only_generated_records_keep_quantity_when_paper_is_incomplete():
    class Harness(SequenceOperations):
        def _config_key(self):
            return "fixture"
    window = Harness()
    window.template = model_for()
    window.template.sequences = []
    window.template.pages.append(PageSpec(name="Page 7"))
    window.message = SimpleNamespace(setText=lambda text: None)
    info = window._sequence_info(None)
    assert info["metadata"]["record_count"] == 5
    assert info["metadata"]["fields"] == []
    assert info["sample"] == [] and "logical page 7" in info["sample_error"]


def test_unexpected_sample_programming_errors_are_not_suppressed(monkeypatch):
    import composition.designer.sequence_controls as controls

    class Harness(SequenceOperations):
        def _config_key(self):
            return "fixture"
    window = Harness()
    window.template = model_for()
    def failed(*args):
        raise RuntimeError("unexpected sample error")
    monkeypatch.setattr(controls, "sequence_record", failed)
    with pytest.raises(RuntimeError, match="unexpected sample error"):
        window._sequence_info(None)


def test_saved_incomplete_project_reopens_for_paper_correction(qt_application, monkeypatch, tmp_path):
    from composition.designer.workspace import CompositionWindow
    from composition.template.serializer import load_project, save_project
    from tests.composition.test_workspace import close_window

    monkeypatch.setattr(CompositionWindow, "_load_windows_fonts", lambda self: None)
    monkeypatch.setattr(CompositionWindow, "_render_preview", lambda self: None)
    model = model_for()
    model.pages.append(PageSpec(name="Page 7"))
    target = save_project(model, tmp_path / "unfinished.pdcx")
    window = CompositionWindow()
    try:
        window._apply_template(load_project(target).to_dict())
        assert len(window.template.pages) == 7 and window.record_count == 5
        assert "logical page 7" in window._store()["sample_error"]
        assert window.actions["media"].isEnabled()
        with pytest.raises(CompositionError, match="no assigned Stock"):
            build_print_plan(window.template, 5)
    finally:
        close_window(window)


def test_incomplete_designer_draft_still_blocks_formal_production_review(tmp_path):
    from dataclasses import asdict

    from composition.production.model import ProductionJob
    from composition.review.service import create_review, validate_snapshot

    model = model_for()
    model.pages.append(PageSpec(name="Page 7"))
    output = tmp_path / "production"
    context = {"kind": "template", "label": "Incomplete paper draft",
               "job": asdict(ProductionJob(model.to_dict(), "", str(output)))}
    directory = tmp_path / "work"
    result = create_review(directory, context)
    assert result["status"] == "blocked"
    assert "no assigned Stock" in str(result["issues"])
    assert not output.exists()
    with pytest.raises(CompositionError):
        validate_snapshot(directory, result["snapshot_id"], result["context"], warnings_acknowledged=True)
