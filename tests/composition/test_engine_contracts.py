from __future__ import annotations

import json
import subprocess
import sys

import fitz
import pytest
from PIL import Image

from composition.engine.assets import asset_root
from composition.engine.fonts import load_font
from composition.engine.renderer import import_background, render_preview
from composition.template.model import CompositionError, Element, FontSpec, Template
from composition.template.serializer import load_project, save_project

pytestmark = pytest.mark.skipif(
    not (asset_root() / "fonts" / "NotoSans-Regular.ttf").exists(), reason="Prepared fonts required."
)


def test_headless_engine_never_imports_qt(tmp_path):
    command = (
        "import sys; from composition.production.generator import generate; "
        "from composition.engine.renderer import render_preview; "
        "assert not any(name.startswith('PyQt') for name in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_windowless_worker_protocol(tmp_path):
    target = tmp_path / "preview.pdf"
    events = tmp_path / "events.jsonl"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"task": "preview", "template": Template().to_dict(),
                                  "target": str(target), "events_file": str(events)}), encoding="utf-8")
    script = (
        "import sys; from composition.worker import main; sys.stdout=None; "
        "raise SystemExit(main(sys.argv[1:]))"
    )
    result = subprocess.run([sys.executable, "-c", script, str(request)], capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(events.read_text(encoding="utf-8"))["event"] == "result"
    with fitz.open(target) as doc:
        assert doc.page_count == 1


def test_shapes_images_and_saved_assets_survive_original_removal(tmp_path):
    source = tmp_path / "image.png"
    Image.new("RGB", (20, 20), "#ff0000").save(source)
    template = Template(elements=[
        Element(type="image", image=str(source), width_mm=30, height_mm=30),
        Element(type="rectangle", x_mm=70, fill="#0000ff", width_mm=30, height_mm=30),
        Element(type="line", y_mm=80, width_mm=80, height_mm=.1),
    ])
    project = save_project(template, tmp_path / "layout.pdcx")
    source.unlink()
    loaded = load_project(project)
    raw = render_preview(loaded, {})
    with fitz.open(stream=raw, filetype="pdf") as doc:
        pix = doc[0].get_pixmap()
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        assert image.getpixel((70, 70)) == (255, 0, 0)
        assert image.getpixel((210, 70)) == (0, 0, 255)


def test_exact_custom_face_and_restricted_embedding(tmp_path):
    from fontTools.ttLib import TTFont
    original = asset_root() / "fonts" / "NotoSans-Regular.ttf"
    with pytest.raises(CompositionError, match="exact selected face"):
        load_font(FontSpec(file=str(original), bold=True))
    restricted = tmp_path / "restricted.ttf"
    with TTFont(original) as font:
        font["OS/2"].fsType = 2
        font.save(restricted)
    with pytest.raises(CompositionError, match="permit outline embedding"):
        load_font(FontSpec(file=str(restricted)))


def test_background_cannot_overwrite_original(tmp_path):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(source)
    before = source.read_bytes()
    with pytest.raises(CompositionError, match="overwrite"):
        import_background(source, 0, source)
    assert source.read_bytes() == before


@pytest.mark.parametrize("template", [
    {"template_version": True},
    {"template_version": 1, "elements": None},
    {"template_version": 1, "data": {"mapping": []}},
    {"template_version": 1, "data": {"header": "yes"}},
])
def test_untrusted_schema_errors_are_actionable(template):
    with pytest.raises(CompositionError):
        Template.from_dict(template)


def test_existing_core_exports_keep_their_identity():
    from core import PdfEngine, SettingsManager, parse_page_range
    from core.pdf_engine import PdfEngine as Engine
    from core.pdf_engine import parse_page_range as parse
    from core.settings import SettingsManager as Settings
    assert PdfEngine is Engine
    assert SettingsManager is Settings
    assert parse_page_range is parse
