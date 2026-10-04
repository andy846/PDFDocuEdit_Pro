from __future__ import annotations

import hashlib

import fitz
import pytest

from composition.engine.assets import asset_root
from composition.engine.renderer import import_background, render_preview
from composition.template.model import CompositionError, Element, FontSpec, Template

pytestmark = pytest.mark.skipif(
    not (asset_root() / "fonts" / "NotoSans-Regular.ttf").exists(),
    reason="Pinned composition fonts are prepared by the build/CI asset step.",
)


def test_unicode_mixed_text_and_exact_page_size():
    template = Template(elements=[
        Element(value="Account: {{Account}}", height_mm=20),
        Element(value="{{Name}}", y_mm=50, height_mm=20, font=FontSpec(family="Noto Sans CJK HK")),
    ])
    raw = render_preview(template, {"Account": "000123", "Name": "\u9999\u6e2f\u5ba2\u6236"})
    with fitz.open(stream=raw, filetype="pdf") as doc:
        assert doc.page_count == 1
        assert abs(doc[0].rect.width - 210 * 72 / 25.4) < 0.001
        assert "Account: 000123" in doc[0].get_text()
        assert "\u9999\u6e2f\u5ba2\u6236" in doc[0].get_text()
        assert all(doc.extract_font(font[0])[3] for font in doc[0].get_fonts())


def test_static_background_remains_visually_identical_and_source_unchanged(tmp_path):
    source = tmp_path / "company.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "Company Statement")
        page.draw_rect(fitz.Rect(10, 70, 400, 400), color=(0, 0, 1))
        doc.save(source)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    background = tmp_path / "background.pdf"
    width, height = import_background(source, 0, background)
    template = Template(width_mm=width, height_mm=height, background=str(background))
    raw = render_preview(template, {})
    with fitz.open(source) as before, fitz.open(stream=raw, filetype="pdf") as after:
        assert before[0].get_pixmap().samples == after[0].get_pixmap().samples
        assert "Company Statement" in after[0].get_text()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_overflow_missing_glyph_and_missing_field_are_errors():
    template = Template(elements=[Element(width_mm=20, height_mm=8, value="{{Text}}")])
    with pytest.raises(CompositionError, match="Record 42.*field Text.*overflows"):
        render_preview(template, {"Text": "a long line " * 200}, 42)
    with pytest.raises(CompositionError, match="Missing field"):
        render_preview(template, {})
    with pytest.raises(CompositionError, match="cannot render"):
        render_preview(Template(elements=[Element(value="\u9999\u6e2f")]), {})


def test_code128_and_qr_decode_exact_payloads():
    from PIL import Image
    try:
        from pyzbar.pyzbar import decode
    except ImportError:
        pytest.skip("Native zbar decoder is exercised by the Windows full suite.")

    template = Template(elements=[
        Element(type="code128", value="{{Account}}", width_mm=100, height_mm=20),
        Element(type="qr", value="{{Name}}", y_mm=70, width_mm=45, height_mm=45),
    ])
    raw = render_preview(template, {"Account": "00012345", "Name": "Customer 001"})
    with fitz.open(stream=raw, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        values = {code.data.decode("utf-8") for code in decode(image)}
    assert values == {"00012345", "Customer 001"}


def test_barcode_size_and_payload_errors():
    with pytest.raises(CompositionError, match="minimum module"):
        render_preview(Template(elements=[Element(type="code128", value="123456789", width_mm=5)]), {})
    with pytest.raises(CompositionError, match="ASCII"):
        render_preview(Template(elements=[Element(type="code128", value="\u9999\u6e2f")]), {})


@pytest.mark.parametrize("encrypted", [False, True])
def test_invalid_background_reports_error_and_releases_reader(tmp_path, encrypted):
    background = tmp_path / "invalid-background.pdf"
    with fitz.open() as doc:
        doc.new_page()
        if encrypted:
            doc.save(background, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
        else:
            doc.new_page()
            doc.save(background)
    with pytest.raises(CompositionError, match="unencrypted single-page PDF"):
        render_preview(Template(background=str(background)), {})
    background.unlink()
    assert not background.exists()
