"""Image-pixel redaction for spot-colour scans without modifying shared sources."""

import pytest

from core.annotations import apply_redaction_marks, redact
from core.pdf_backend import fitz
from core.pdf_engine import PdfEngine, PdfEngineError
from core.redaction_images import redaction_spot_image_count


def spot_image(doc, page, *, space="Separation", mask=False):
    samples = bytes([255 if 20 <= x < 50 and 20 <= y < 50 else (x + y) % 180
                     for y in range(100) for x in range(100)])
    pix = fitz.Pixmap(fitz.csGRAY, 100, 100, samples, False)
    xref = page.insert_image(fitz.Rect(0, 0, 100, 100), pixmap=pix)
    indexed = space.startswith("Indexed/")
    base_space = space.removeprefix("Indexed/")
    names = "/Black" if base_space == "Separation" else "[/Black]"
    colour = f"[/{base_space} {names} /DeviceCMYK << /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 0 0 1] /N 1 >>]"
    if indexed:
        colour = f"[/Indexed {colour} 255 <{bytes(range(256)).hex()}>]"
    doc.xref_set_key(xref, "ColorSpace", colour)
    if mask:
        smask = doc.get_new_xref()
        doc.update_object(smask, "<< /Type /XObject /Subtype /Image /Width 100 /Height 100 /BitsPerComponent 8 /ColorSpace /DeviceGray >>")
        doc.update_stream(smask, bytes([180] * 10000))
        doc.xref_set_key(xref, "SMask", f"{smask} 0 R")
    return xref


def pixel(page, point):
    return page.get_pixmap().pixel(*point)


@pytest.mark.parametrize("space", ["Separation", "DeviceN", "Indexed/Separation", "Indexed/DeviceN"])
@pytest.mark.parametrize("mask", [False, True])
def test_spot_image_redaction_removes_pixels_preserves_unmarked_appearance(space, mask):
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        original = spot_image(doc, page, space=space, mask=mask)
        outside = pixel(page, (70, 70))
        assert max(pixel(page, (30, 30))) < 255
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert redaction_spot_image_count(doc) == 1
        assert apply_redaction_marks(doc) == 1
        page = doc[0]
        assert list(page.annots() or []) == []
        assert min(pixel(page, (30, 30))) >= 250
        assert max(abs(a - b) for a, b in zip(outside, pixel(page, (70, 70)), strict=True)) <= 2
        assert tuple(page.rect) == (0, 0, 100, 100)
        images = page.get_images(full=True)
        assert images and all(entry[0] != original for entry in images)
        redacted = fitz.Pixmap(doc, images[0][0])
        assert redacted.width == redacted.height == 100
        assert not any("Redact" in str(a.type) for a in page.annots() or [])


def test_spot_conversion_does_not_modify_shared_image_or_unmarked_page():
    with fitz.open() as doc:
        first = doc.new_page(width=100, height=100)
        image = spot_image(doc, first)
        second = doc.new_page(width=100, height=100)
        second.insert_image(fitz.Rect(0, 0, 100, 100), xref=image)
        before_image = doc.xref_object(image), doc.xref_stream(image)
        before_other = second.get_pixmap().samples
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert apply_redaction_marks(doc) == 1
        assert before_image == (doc.xref_object(image), doc.xref_stream(image))
        assert doc[1].get_pixmap().samples == before_other
        assert doc[1].get_images()[0][0] == image
        assert min(pixel(doc[0], (30, 30))) >= 250


def test_nested_shared_form_spot_redaction_keeps_other_page_unchanged():
    with fitz.open() as source, fitz.open() as doc:
        source_page = source.new_page(width=100, height=100)
        spot_image(source, source_page)
        for _ in range(2):
            page = doc.new_page(width=100, height=100)
            page.show_pdf_page(page.rect, source, 0)
        before_other = doc[1].get_pixmap().samples
        original_objects = {xref: (doc.xref_object(xref), doc.xref_stream(xref))
                            for xref in range(1, doc.xref_length()) if doc.xref_is_stream(xref)}
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert apply_redaction_marks(doc) == 1
        assert min(pixel(doc[0], (30, 30))) >= 250
        assert doc[1].get_pixmap().samples == before_other
        for xref, original in original_objects.items():
            assert (doc.xref_object(xref), doc.xref_stream(xref)) == original


def test_spot_redaction_sanitised_save_removes_original_image_stream(tmp_path):
    source = tmp_path / "spot.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        image = spot_image(doc, page)
        old_samples = doc.xref_stream(image)
        doc.save(source)
    engine = PdfEngine()
    engine.open(source)
    try:
        with engine.mutation_transaction("Apply Redactions"):
            redact(engine.document, 0, [fitz.Rect(20, 20, 50, 50)])
            assert apply_redaction_marks(engine.document) == 1
            engine.mark_modified(requires_sanitized_save=True)
        output = engine.save(tmp_path / "redacted.pdf")
        with fitz.open(output) as saved:
            assert min(pixel(saved[0], (30, 30))) >= 250
            assert not any(saved.xref_stream(xref) == old_samples
                           for xref in range(1, saved.xref_length()) if saved.xref_is_stream(xref))
            assert not list(saved[0].annots() or [])
            image_objects = [xref for xref in range(1, saved.xref_length()) if saved.xref_is_image(xref)]
            assert len(image_objects) == 1
            actual_pixels = fitz.Pixmap(fitz.csRGB, fitz.Pixmap(saved, image_objects[0]))
            assert min(actual_pixels.pixel(30, 30)) >= 250
    finally:
        engine.close()


def test_nonintersecting_spot_image_and_disabled_image_redaction_are_untouched():
    for images, rect in ((fitz.PDF_REDACT_IMAGE_PIXELS, fitz.Rect(110, 10, 140, 40)),
                        (fitz.PDF_REDACT_IMAGE_NONE, fitz.Rect(20, 20, 50, 50))):
        with fitz.open() as doc:
            page = doc.new_page(width=150, height=100)
            image = spot_image(doc, page)
            before = doc.xref_object(image), doc.xref_stream(image)
            redact(doc, 0, [rect])
            assert apply_redaction_marks(doc, images=images) == 1
            assert before == (doc.xref_object(image), doc.xref_stream(image))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_spot_image_redaction_preserves_rotation_and_crop(rotation):
    with fitz.open() as doc:
        page = doc.new_page(width=120, height=120)
        spot_image(doc, page)
        page.set_cropbox(fitz.Rect(10, 10, 110, 110))
        page.set_rotation(rotation)
        before = tuple(page.rect), tuple(page.cropbox), page.rotation
        redact(doc, 0, [fitz.Rect(10, 10, 40, 40)])
        assert apply_redaction_marks(doc) == 1
        page = doc[0]
        assert before == (tuple(page.rect), tuple(page.cropbox), page.rotation)
        assert not list(page.annots() or [])
        assert page.get_images()[0][5] not in {"Separation", "DeviceN"}


def test_spot_conversion_uses_inherited_resources_without_changing_parent():
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        spot_image(doc, page)
        parent = int(doc.xref_get_key(page.xref, "Parent")[1].split()[0])
        resources = doc.xref_get_key(page.xref, "Resources")[1]
        doc.xref_set_key(parent, "Resources", resources)
        doc.xref_set_key(page.xref, "Resources", "null")
        original_parent = doc.xref_object(parent)
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert apply_redaction_marks(doc) == 1
        assert doc.xref_object(parent) == original_parent
        assert min(pixel(doc[0], (30, 30))) >= 250


def test_spot_conversion_reports_each_affected_image_once():
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        image = spot_image(doc, page)
        redact(doc, 0, [fitz.Rect(20, 20, 30, 30), fitz.Rect(35, 35, 45, 45)])
        conversions = []
        assert apply_redaction_marks(doc, image_conversions=conversions) == 2
        assert conversions == [(0, image, "Separation", "DeviceCMYK")]


def test_spot_conversion_failure_rolls_back_all_pages_and_stays_saveable(tmp_path, monkeypatch):
    import core.annotations as annotations

    source = tmp_path / "two-pages.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            page = doc.new_page(width=100, height=100)
            spot_image(doc, page)
            page.add_redact_annot(fitz.Rect(20, 20, 50, 50))
        doc.save(source)
    engine = PdfEngine()
    engine.open(source)
    before = [p.get_pixmap().samples for p in engine.document]
    original = annotations.prepare_spot_images

    def fail_second_page(page, rects):
        if page.number == 1:
            raise RuntimeError("Injected image conversion failure")
        return original(page, rects)

    monkeypatch.setattr(annotations, "prepare_spot_images", fail_second_page)
    try:
        with pytest.raises(PdfEngineError, match="restored"):
            with engine.mutation_transaction("Apply Redactions"):
                apply_redaction_marks(engine.document)
                engine.mark_modified(requires_sanitized_save=True)
        assert [p.get_pixmap().samples for p in engine.document] == before
        assert all(list(p.annots() or []) for p in engine.document)
        assert not engine.is_modified
        assert not engine._requires_sanitized_save
        saved = engine.save(tmp_path / "after-rollback.pdf")
        with fitz.open(saved) as doc:
            assert [p.get_pixmap().samples for p in doc] == before
    finally:
        engine.close()


def test_failed_backend_apply_does_not_report_spot_conversion_as_success(monkeypatch):
    from core.annotations import AnnotationValidationError

    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        spot_image(doc, page)
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        conversions = []
        monkeypatch.setattr(fitz.Page, "apply_redactions", lambda *a, **k: False)
        with pytest.raises(AnnotationValidationError, match="page 1"):
            apply_redaction_marks(doc, image_conversions=conversions)
        assert conversions == []



def test_repeated_spot_image_keeps_unmarked_placement_visible():
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        image = spot_image(doc, page)
        page.insert_image(fitz.Rect(100, 0, 200, 100), xref=image)
        before = page.get_pixmap().pixel(130, 30)
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert apply_redaction_marks(doc) == 1
        assert min(pixel(doc[0], (30, 30))) >= 250
        assert pixel(doc[0], (130, 30)) == before


@pytest.mark.parametrize("base", ["DeviceRGB", "DeviceGray"])
def test_ordinary_indexed_images_keep_existing_redaction_path(base):
    with fitz.open() as doc:
        page = doc.new_page(width=100, height=100)
        image = spot_image(doc, page)
        palette = bytes(value for value in range(256) for _ in range(3 if base == "DeviceRGB" else 1))
        doc.xref_set_key(image, "ColorSpace", f"[/Indexed /{base} 255 <{palette.hex()}>]")
        redact(doc, 0, [fitz.Rect(20, 20, 50, 50)])
        assert redaction_spot_image_count(doc) == 0
        conversions = []
        assert apply_redaction_marks(doc, image_conversions=conversions) == 1
        assert conversions == []
        assert min(pixel(doc[0], (30, 30))) >= 250
