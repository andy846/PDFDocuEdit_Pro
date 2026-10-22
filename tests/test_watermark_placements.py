"""Owned printable content stays editable without changing unrelated PDF data."""
from dataclasses import replace

import numpy as np
import pytest

from core.pdf_backend import fitz
from core.watermarks import (
    WatermarkError,
    WatermarkSpec,
    add_watermark,
    list_watermarks,
    remove_watermark,
    update_watermark_geometry,
    watermark_spec,
)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
def test_visible_watermark_is_rotation_invariant_and_persistent(tmp_path, rotation, cropped):
    with fitz.open() as doc:
        width, height = (595, 842) if rotation % 180 == 0 else (842, 595)
        page = doc.new_page(width=width + 40, height=height + 60)
        if cropped:
            page.set_cropbox(fitz.Rect(20, 30, width + 20, height + 30))
        else:
            page.set_mediabox(fitz.Rect(0, 0, width, height))
        page.set_rotation(rotation)
        spec = WatermarkSpec(text="Asymmetric ABC ->", rotation=31, x_mm=12, y_mm=-8)
        add_watermark(page, spec)
        entry = list_watermarks(page)[0]
        visible = entry["rect"] * page.rotation_matrix
        assert visible.tl.x + visible.width / 2 == pytest.approx(595 / 2 + 12 * 72 / 25.4, abs=.01)
        assert visible.tl.y + visible.height / 2 == pytest.approx(842 / 2 - 8 * 72 / 25.4, abs=.01)
        pixels = page.get_pixmap(annots=False)
        assert min(pixels.samples) < 250
        with fitz.open() as ref:
            ref_page = ref.new_page(width=595, height=842)
            add_watermark(ref_page, spec)
            expected = ref_page.get_pixmap(annots=False)
            error = np.abs(np.frombuffer(pixels.samples, np.uint8).astype(float)
                           - np.frombuffer(expected.samples, np.uint8).astype(float)).mean()
            assert error < .2
        path = tmp_path / "watermarked.pdf"
        doc.save(path, garbage=4, deflate=True)
    with fitz.open(path) as saved:
        page = saved[0]
        entry = list_watermarks(page)[0]
        assert entry["id"]
        assert watermark_spec(page, entry["xref"]).text == spec.text
        old = entry["rect"]
        target = fitz.Rect(old.x0 + old.width * .1, old.y0 + old.height * .1,
                           old.x1 - old.width * .1, old.y1 - old.height * .1)
        changed = update_watermark_geometry(page, entry["xref"], target)
        assert changed is not None
        assert tuple(list_watermarks(page)[0]["rect"]) == pytest.approx(tuple(target))
        with fitz.open() as ref:
            reference_page = ref.new_page(width=595, height=842)
            add_watermark(reference_page, watermark_spec(page, changed))
            actual = np.frombuffer(page.get_pixmap().samples, np.uint8).astype(float)
            expected = np.frombuffer(reference_page.get_pixmap().samples, np.uint8).astype(float)
            assert np.abs(actual - expected).mean() < .2
        assert remove_watermark(page, changed)
        assert not list_watermarks(page)
        assert min(page.get_pixmap(annots=False).samples) == 255


def test_duplicate_placement_is_copy_on_write_and_external_stream_merge_is_blocked():
    with fitz.open() as doc:
        page = doc.new_page()
        add_watermark(page, WatermarkSpec(text="OWNER"))
        doc.fullcopy_page(0)
        # fullcopy_page merges streams and drops private stream dictionaries;
        # explicitly exercise shared content, as the existing image tests do.
        doc[1].set_contents(list_watermarks(doc[0])[0]["xref"])
        page = doc[0]
        entry = list_watermarks(page)[0]
        original = list_watermarks(doc[1])[0]["rect"]
        new = update_watermark_geometry(page, entry["xref"], entry["rect"] + (20, 0, 20, 0))
        assert tuple(list_watermarks(doc[1])[0]["rect"]) == tuple(original)
        stream = doc.xref_stream(new)
        doc.update_stream(new, stream + b"\n0 0 10 10 re f\n")
        with pytest.raises(WatermarkError):
            remove_watermark(page, new)
        assert doc.xref_stream(new).endswith(b"re f\n")


def test_image_resource_is_embedded_and_reusable_after_original_deleted(tmp_path):
    from PIL import Image
    path = tmp_path / "mark.png"
    Image.new("RGBA", (160, 80), (200, 20, 40, 120)).save(path)
    with fitz.open() as doc:
        page = doc.new_page()
        add_watermark(page, WatermarkSpec(mode="image", rotation=19), image=path.read_bytes())
        path.unlink()
        data = doc.tobytes(garbage=4)
    with fitz.open(stream=data, filetype="pdf") as doc:
        from core.watermarks import watermark_image
        page = doc[0]
        entry = list_watermarks(page)[0]
        embedded = watermark_image(page, entry["xref"])
        assert embedded
        add_watermark(page, replace(watermark_spec(page, entry["xref"]), opacity=.7), image=embedded)
        assert len(list_watermarks(page)) == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_watermark_never_mutates_document(value):
    with fitz.open() as doc:
        page = doc.new_page()
        before = page.get_contents()
        with pytest.raises(WatermarkError):
            add_watermark(page, WatermarkSpec(rotation=value))
        assert page.get_contents() == before


def test_batch_watermarks_reuse_fonts_and_do_not_shrink_after_a_small_page():
    from core.annotations import add_watermark_text
    with fitz.open() as doc:
        for width in (180, 595, 595):
            doc.new_page(width=width, height=842)
        add_watermark_text(doc, [0, 1, 2], "BATCH RESOURCE", fontsize=64, rotation=0)
        assert len({font[0] for page in doc for font in page.get_fonts(full=True)}) == 1
        widths = [list_watermarks(page)[0]["rect"].width for page in doc]
        assert widths[1] == pytest.approx(widths[2])
        assert widths[1] > widths[0]


@pytest.mark.parametrize("change", ["rotate", "crop"])
def test_image_properties_roundtrip_keeps_absolute_size_after_page_change(tmp_path, change):
    from PIL import Image

    from core.watermarks import watermark_image
    path = tmp_path / "roundtrip.png"
    Image.new("RGB", (160, 80), "red").save(path)
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        add_watermark(page, WatermarkSpec(mode="image", rotation=0), image=path.read_bytes())
        if change == "rotate":
            page.set_rotation(90)
        else:
            page.set_cropbox(fitz.Rect(50, 50, 545, 792))
        original = page.get_pixmap().samples
        entry = list_watermarks(page)[0]
        xref = add_watermark(page, watermark_spec(page, entry["xref"]),
                             image=watermark_image(page, entry["xref"]))
        remove_watermark(page, entry["xref"])
        assert tuple(list_watermarks(page)[0]["rect"]) == pytest.approx(tuple(entry["rect"]), abs=.01)
        error = np.abs(np.frombuffer(page.get_pixmap().samples, np.uint8).astype(float)
                       - np.frombuffer(original, np.uint8).astype(float)).mean()
        assert error < .05
        assert remove_watermark(page, xref)


@pytest.mark.parametrize("origin", [[], [0], [0, 0, 0], "oops", None])
def test_malformed_owned_metadata_does_not_break_page_open(origin):
    import json
    with fitz.open() as doc:
        page = doc.new_page()
        xref = add_watermark(page, WatermarkSpec())
        kind, raw = doc.xref_get_key(xref, "PDFdocuEditWatermark")
        data = json.loads(raw)
        data["origin"] = origin
        doc.xref_set_key(xref, "PDFdocuEditWatermark", fitz.get_pdf_str(json.dumps(data)))
        assert list_watermarks(page) == []
        assert min(page.get_pixmap().samples) < 255


@pytest.mark.parametrize("tiny", ["autofit", "resize"])
def test_small_fitted_watermark_remains_editable_after_save(tiny):
    with fitz.open() as doc:
        page = doc.new_page()
        spec = WatermarkSpec(text="A" * 200, fontsize=1000, rotation=0) if tiny == "autofit" else WatermarkSpec()
        xref = add_watermark(page, spec)
        if tiny == "resize":
            entry = list_watermarks(page)[0]
            r = entry["rect"]
            xref = update_watermark_geometry(page, xref, fitz.Rect(r.x0, r.y0, r.x0 + 2, r.y0 + 2))
        with fitz.open(stream=doc.tobytes(garbage=4), filetype="pdf") as saved:
            entries = list_watermarks(saved[0])
            assert len(entries) == 1
            assert remove_watermark(saved[0], entries[0]["xref"])


@pytest.mark.parametrize("matrix", ["1e999 0 0 1 0 0", "0 0 0 0 0 0"])
def test_invalid_owned_content_transform_blocks_destructive_edit(matrix):
    with fitz.open() as doc:
        page = doc.new_page()
        xref = add_watermark(page, WatermarkSpec())
        stream = doc.xref_stream(xref).strip().split()
        name = next(part for part in stream if part.startswith(b"/"))
        doc.update_stream(xref, b"q " + matrix.encode() + b" cm " + name + b" Do Q")
        with pytest.raises(WatermarkError):
            remove_watermark(page, xref)


@pytest.mark.parametrize("rect", [[], [1], [1, 2, 3], [1, 2, 3, 4, 5], {}, "bad", 5])
def test_malformed_owned_rectangle_is_ignored_without_hiding_pdf(rect):
    import json
    with fitz.open() as doc:
        page = doc.new_page()
        xref = add_watermark(page, WatermarkSpec())
        data = json.loads(doc.xref_get_key(xref, "PDFdocuEditWatermark")[1])
        data["rect"] = rect
        doc.xref_set_key(xref, "PDFdocuEditWatermark", fitz.get_pdf_str(json.dumps(data)))
        assert list_watermarks(page) == []
        assert min(page.get_pixmap().samples) < 255


@pytest.mark.parametrize("change", ["placement", "resource", "nested-resource"])
def test_external_watermark_resource_changes_are_not_removed(change):
    with fitz.open() as doc:
        page = doc.new_page()
        xref = add_watermark(page, WatermarkSpec())
        if change == "placement":
            stream = doc.xref_stream(xref).strip().split()
            name = next(part for part in stream if part.startswith(b"/"))
            doc.update_stream(xref, b"q 1 0 0 1 10 0 cm " + name + b" Do Q")
        else:
            resource = next(item[0] for item in page.get_xobjects() if (item[2] == 0) == (change == "resource"))
            doc.update_stream(resource, doc.xref_stream(resource) + b"\n0 0 10 10 re f\n")
        with pytest.raises(WatermarkError):
            remove_watermark(page, xref)


def test_watermark_survives_insert_pdf_resource_grafting():
    with fitz.open() as doc, fitz.open() as output:
        page = doc.new_page()
        page.insert_text((20, 30), "KEEP ORIGINAL")
        add_watermark(page, WatermarkSpec(text="COPY"))
        output.insert_pdf(doc)
        entry = list_watermarks(output[0])[0]
        assert watermark_spec(output[0], entry["xref"]).text == "COPY"
        assert remove_watermark(output[0], entry["xref"])
        assert "KEEP ORIGINAL" in output[0].get_text()


def test_unicode_watermark_embeds_font_and_keeps_original_content():
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((20, 30), "KEEP ORIGINAL")
        add_watermark(page, WatermarkSpec(text="測試中文 WATERMARK"))
        assert "測試中文 WATERMARK" in page.get_text()
        assert "KEEP ORIGINAL" in page.get_text()
        fonts = [font for font in page.get_fonts(full=True) if font[3] != "Helvetica"]
        assert fonts and all(doc.extract_font(font[0])[3] for font in fonts)


def test_changed_embedded_original_image_cannot_be_reused_silently(tmp_path):
    from PIL import Image

    from core.watermarks import watermark_image
    path = tmp_path / "asset.png"
    Image.new("RGB", (20, 10), "red").save(path)
    with fitz.open() as doc:
        page = doc.new_page()
        xref = add_watermark(page, WatermarkSpec(mode="image", rotation=0), image=path.read_bytes())
        asset = int(doc.xref_get_key(xref, "PDFdocuEditWatermarkAsset")[1].split()[0])
        doc.update_stream(asset, b"changed externally")
        with pytest.raises(WatermarkError):
            watermark_image(page, xref)
