from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from core.overlay import (
    OverlayOptions,
    destination_rect,
    render_overlay_preview,
    scan_overlay_inputs,
    template_page_number,
)
from core.tools import ToolError, overlay_pdf, overlay_pdfs


def make_pdf(path: Path, pages: int = 1, *, color: tuple[float, float, float] | None = None) -> Path:
    with fitz.open() as document:
        for _ in range(pages):
            page = document.new_page(width=100, height=100)
            if color is not None:
                page.draw_rect(page.rect, color=None, fill=color)
        document.save(path)
    return path


def test_page_pairing_and_geometry() -> None:
    assert [template_page_number(i, 2, "repeat_last") for i in range(4)] == [0, 1, 1, 1]
    assert [template_page_number(i, 2, "cycle") for i in range(4)] == [0, 1, 0, 1]
    assert [template_page_number(i, 2, "matching_only") for i in range(4)] == [0, 1, None, None]
    target = fitz.Rect(0, 0, 200, 100)
    source = fitz.Rect(0, 0, 50, 50)
    assert destination_rect(target, source, OverlayOptions()) == fitz.Rect(50, 0, 150, 100)
    actual = OverlayOptions(scale_mode="actual", alignment="top-right", offset_x_mm=25.4)
    assert destination_rect(target, source, actual) == fitz.Rect(222, 0, 272, 50)
    rotated = OverlayOptions(scale_mode="actual", rotation=90)
    assert destination_rect(target, fitz.Rect(0, 0, 40, 60), rotated) == fitz.Rect(70, 30, 130, 70)
    with pytest.raises(ValueError):
        OverlayOptions(offset_x_mm=float("nan"))


def test_preflight_reports_collision_and_invalid_input(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    source_a = make_pdf(tmp_path / "a" / "sample.pdf")
    source_b = make_pdf(tmp_path / "b" / "sample.pdf")
    plan = scan_overlay_inputs(template, [source_a, source_b], tmp_path, "_overlay", False)
    assert not plan.valid
    assert plan.jobs[0].pages == 1
    assert "same output" in plan.jobs[1].problem
    assert "Template cannot" in scan_overlay_inputs(template, [template], tmp_path, "_x", False).jobs[0].problem


def test_overlay_preview_matches_export_and_layer_order(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "red.pdf", color=(1, 0, 0))
    target = make_pdf(tmp_path / "blue.pdf", color=(0, 0, 1))
    options = OverlayOptions(scale_mode="actual", alignment="center")
    before, after, count = render_overlay_preview(template, target, 0, options)
    assert count == 1 and before != after
    output = overlay_pdf(template, target, tmp_path / "result.pdf", options=options)
    with fitz.open(output) as document:
        saved = document[0].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
    assert after == saved
    background = overlay_pdf(
        template, target, tmp_path / "background.pdf",
        options=OverlayOptions(layer="background"),
    )
    with fitz.open(background) as document, fitz.open(target) as original:
        assert document[0].get_pixmap().samples == original[0].get_pixmap().samples


def test_default_overlay_renders_like_existing_full_page_operation(tmp_path: Path) -> None:
    template = tmp_path / "template.pdf"
    with fitz.open() as document:
        page = document.new_page(width=60, height=100)
        page.draw_rect(page.rect, color=None, fill=(1, 0, 0))
        document.save(template)
    target = make_pdf(tmp_path / "target.pdf", color=(0, 0, 1))
    legacy = tmp_path / "legacy.pdf"
    with fitz.open(target) as document, fitz.open(template) as source:
        document[0].show_pdf_page(document[0].rect, source, 0, overlay=True, keep_proportion=True)
        document.save(legacy)
    output = overlay_pdf(template, target, tmp_path / "new.pdf")
    with fitz.open(legacy) as old, fitz.open(output) as new:
        assert old[0].get_pixmap().samples == new[0].get_pixmap().samples


def test_cancel_does_not_replace_existing_output(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf")
    target = make_pdf(tmp_path / "target.pdf", pages=2)
    output = tmp_path / "result.pdf"
    output.write_bytes(b"original")
    progress = []
    with pytest.raises(ToolError, match="cancelled"):
        overlay_pdf(
            template, target, output,
            progress=lambda done, total, _: progress.append((done, total)),
            is_cancelled=lambda: bool(progress),
        )
    assert output.read_bytes() == b"original"
    assert not list(tmp_path.glob(".result-*.pdf"))


def test_batch_continues_after_one_unreadable_target(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a PDF")
    good = make_pdf(tmp_path / "good.pdf")
    reports = []
    outputs = overlay_pdfs(
        template, [bad, good], tmp_path, options=OverlayOptions(mapping="cycle"),
        on_item=reports.append, continue_on_error=True,
    )
    assert [report.status for report in reports] == ["failed", "completed"]
    assert outputs == [tmp_path / "good_overlay.pdf"]


def test_batch_cancel_keeps_completed_file_and_does_not_start_next(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf")
    first = make_pdf(tmp_path / "first.pdf")
    second = make_pdf(tmp_path / "second.pdf")
    reports = []
    outputs = overlay_pdfs(
        template, [first, second], tmp_path, on_item=reports.append,
        is_cancelled=lambda: bool(reports),
    )
    assert outputs == [tmp_path / "first_overlay.pdf"]
    assert [item.status for item in reports] == ["completed"]
    assert not (tmp_path / "second_overlay.pdf").exists()


def test_unsaved_source_snapshot_keeps_original_output_name(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf", color=(1, 0, 0))
    source = make_pdf(tmp_path / "original.pdf")
    snapshot_folder = tmp_path / "working"
    snapshot_folder.mkdir()
    snapshot = make_pdf(snapshot_folder / "original.pdf", color=(0, 0, 1))
    reports = []
    outputs = overlay_pdfs(
        template, [source], tmp_path, source_overrides={source: snapshot},
        on_item=reports.append, options=OverlayOptions(layer="background"),
    )
    assert outputs == [tmp_path / "original_overlay.pdf"]
    assert reports[0].source == source
    assert reports[0].output == outputs[0]
    with fitz.open(outputs[0]) as document, fitz.open(snapshot) as working:
        # A background template leaves the blue snapshot visible.
        assert document[0].get_pixmap().samples == working[0].get_pixmap().samples


def test_template_is_never_replaced_by_an_overlay(tmp_path: Path) -> None:
    template = make_pdf(tmp_path / "template.pdf")
    target = make_pdf(tmp_path / "target.pdf")
    original = template.read_bytes()
    with pytest.raises(ToolError, match="template"):
        overlay_pdf(template, target, template)
    with pytest.raises(ToolError, match="template"):
        overlay_pdfs(template, [template], tmp_path)
    assert template.read_bytes() == original
