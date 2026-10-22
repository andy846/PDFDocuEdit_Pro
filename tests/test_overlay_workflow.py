from __future__ import annotations

from pathlib import Path

import pytest

from core.overlay import (
    OverlayOptions,
    destination_rect,
    render_overlay_preview,
    scan_overlay_inputs,
    template_page_number,
)
from core.pdf_backend import fitz
from core.tools import ToolError, overlay_pdf, overlay_pdfs


@pytest.mark.parametrize("scale", ["fit", "actual"])
@pytest.mark.parametrize("page_size", ["target", "template"])
def test_a4_template_letter_target_output_size_and_preview_match(tmp_path, scale, page_size):
    a4 = (210 * 72 / 25.4, 297 * 72 / 25.4)
    template, target = tmp_path / "a4.pdf", tmp_path / "letter.pdf"
    for path, size, content in ((template, a4, "Template"), (target, (612, 792), "Target")):
        with fitz.open() as doc:
            doc.new_page(width=size[0], height=size[1]).insert_text((30, 80), content)
            doc.save(path)
    original = target.read_bytes(), template.read_bytes()
    options = OverlayOptions(scale_mode=scale, output_page_size=page_size)
    output = overlay_pdf(template, target, tmp_path / "result.pdf", options=options)
    before, after, count, geometry = render_overlay_preview(template, target, 0, options, include_geometry=True)
    expected = a4 if page_size == "template" else (612, 792)
    with fitz.open(output) as result:
        page = result[0]
        assert (page.rect.width, page.rect.height) == pytest.approx(expected, abs=0.001)
        assert "Target" in page.get_text() and "Template" in page.get_text()
        zoom = min(1.5, 1100 / max(612, 792, *expected))
        assert after == page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")
    assert count == 1 and before != after
    assert geometry["after_mm"] == pytest.approx([v * 25.4 / 72 for v in expected], abs=0.001)
    assert (target.read_bytes(), template.read_bytes()) == original


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
def test_template_size_keeps_visible_target_positions_and_document_features(tmp_path, rotation, cropped):
    template, target = tmp_path / "template.pdf", tmp_path / "target.pdf"
    with fitz.open() as doc:
        doc.new_page(width=1000, height=1100).insert_text((30, 40), "Overlay")
        doc.save(template)
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((110, 200), "Target marker")
        page.add_rect_annot(fitz.Rect(110, 240, 200, 260)).update()
        widget = fitz.Widget()
        widget.field_name, widget.field_value = "Name", "Customer"
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.rect = fitz.Rect(110, 300, 220, 320)
        page.add_widget(widget)
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(110, 360, 220, 380), "uri": "https://example.test/"})
        if cropped:
            page.set_cropbox(fitz.Rect(50, 80, 550, 720))
        page.set_rotation(rotation)
        doc.set_metadata({"title": "Original target"})
        doc.set_toc([[1, "Target top", 1]])
        doc.save(target)
    with fitz.open(target) as doc:
        page = doc[0]
        marker = page.search_for("Target marker")[0] * page.rotation_matrix
        annotation = next(page.annots()).rect * page.rotation_matrix
        field = next(page.widgets()).rect * page.rotation_matrix
        link = page.get_links()[0]["from"]
    output = overlay_pdf(template, target, tmp_path / "result.pdf", options=OverlayOptions(output_page_size="template"))
    with fitz.open(output) as doc:
        page = doc[0]
        assert tuple(page.rect) == pytest.approx((0, 0, 1000, 1100), abs=0.001)
        assert tuple(page.search_for("Target marker")[0] * page.rotation_matrix) == pytest.approx(tuple(marker), abs=0.001)
        assert tuple(next(page.annots()).rect * page.rotation_matrix) == pytest.approx(tuple(annotation), abs=0.001)
        field_after = next(page.widgets())
        assert field_after.field_value == "Customer"
        assert tuple(field_after.rect * page.rotation_matrix) == pytest.approx(tuple(field), abs=0.001)
        assert page.get_links()[0]["uri"] == "https://example.test/"
        assert tuple(page.get_links()[0]["from"]) == pytest.approx(tuple(link), abs=0.001)
        assert doc.metadata["title"] == "Original target" and doc.get_toc() == [[1, "Target top", 1]]


@pytest.mark.parametrize("mapping,expected", [
    ("repeat_last", [(200, 300), (300, 400), (300, 400)]),
    ("cycle", [(200, 300), (300, 400), (200, 300)]),
    ("matching_only", [(200, 300), (300, 400), (612, 792)]),
])
def test_output_size_uses_each_paired_template_page(tmp_path, mapping, expected):
    template, target = tmp_path / "template.pdf", tmp_path / "target.pdf"
    with fitz.open() as doc:
        for w, h in ((200, 300), (300, 400)):
            doc.new_page(width=w, height=h).insert_text((20, 50), "Overlay")
        doc.save(template)
    with fitz.open() as doc:
        for _ in range(3):
            doc.new_page(width=612, height=792).insert_text((20, 60), "Target")
        doc.save(target)
    outputs = overlay_pdfs(template, [target], tmp_path, options=OverlayOptions(mapping=mapping, output_page_size="template"))
    with fitz.open(outputs[0]) as doc:
        assert doc.page_count == 3
        assert [(page.rect.width, page.rect.height) for page in doc] == expected


def test_larger_canvas_clips_old_content_without_clipping_the_new_overlay(tmp_path):
    template, target = tmp_path / "a4.pdf", tmp_path / "letter.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=210 * 72 / 25.4, height=297 * 72 / 25.4)
        page.draw_rect(fitz.Rect(10, 810, 30, 830), color=None, fill=(0, 0, 1))
        doc.save(template)
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(60, 810, 80, 830), color=None, fill=(1, 0, 0))
        doc.save(target)
    output = overlay_pdf(template, target, tmp_path / "result.pdf", options=OverlayOptions(output_page_size="template"))
    with fitz.open(output) as doc:
        image = doc[0].get_pixmap(alpha=False)
        assert image.pixel(20, 820) == (0, 0, 255)
        assert image.pixel(70, 820) == (255, 255, 255)


@pytest.mark.parametrize("hidden", [False, True])
def test_resizing_does_not_reveal_clipped_appearances_or_publish_partial_output(tmp_path, hidden):
    template, target = tmp_path / "a4.pdf", tmp_path / "letter.pdf"
    with fitz.open() as doc:
        doc.new_page(width=210 * 72 / 25.4, height=297 * 72 / 25.4).insert_text((30, 50), "Template")
        doc.save(template)
    with fitz.open() as doc:
        page = doc.new_page(width=612, height=792)
        page.insert_text((30, 60), "Target")
        annotation = page.add_rect_annot(fitz.Rect(60, 810, 80, 830))
        if hidden:
            annotation.set_flags(annotation.flags | fitz.PDF_ANNOT_IS_HIDDEN)
        annotation.update()
        doc.save(target)
    original = target.read_bytes()
    output = tmp_path / "result.pdf"
    if hidden:
        overlay_pdf(template, target, output, options=OverlayOptions(output_page_size="template"))
        with fitz.open(output) as doc:
            assert next(doc[0].annots()).flags & fitz.PDF_ANNOT_IS_HIDDEN
        assert target.read_bytes() == original
        return
    with pytest.raises(ValueError, match="clipped annotation or form"):
        overlay_pdf(template, target, output, options=OverlayOptions(output_page_size="template"))
    assert target.read_bytes() == original and not output.exists()


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
