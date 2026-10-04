from __future__ import annotations

import os

import fitz
import pytest
from fontTools.ttLib import TTCollection, TTFont

from composition.engine.assets import asset_root
from composition.engine.renderer import render_preview
from composition.engine.system_fonts import export_face, font_catalogue, inspect_font_file
from composition.template.model import CompositionError, Element, FontSpec, Template
from composition.template.serializer import load_project, save_project


def test_collection_face_export_and_portable_save(tmp_path):
    regular = asset_root() / "fonts/NotoSans-Regular.ttf"
    bold = asset_root() / "fonts/NotoSans-Bold.ttf"
    if not regular.exists():
        pytest.skip("Prepared fonts required")
    collection = TTCollection()
    collection.fonts = [TTFont(regular), TTFont(bold)]
    path = tmp_path / "two-faces.ttc"
    try:
        collection.save(path)
    finally:
        for font in collection.fonts:
            font.close()
    faces = inspect_font_file(path)
    assert len(faces) == 2
    assert faces[0]["style"] == "Regular"
    assert faces[1]["style"] == "Bold"
    exact = export_face(faces[1], tmp_path / "export")
    with TTFont(exact["file"]) as font:
        assert font["OS/2"].usWeightClass >= 700
    template = Template(elements=[Element(value="Selected bold face",
                       font=FontSpec(family=exact["family"], file=exact["file"]))])
    before = render_preview(template, {})
    project = save_project(template, tmp_path / "saved.pdcx")
    os.remove(exact["file"])
    after = render_preview(load_project(project), {})
    with fitz.open(stream=before, filetype="pdf") as original, fitz.open(stream=after, filetype="pdf") as reopened:
        assert original[0].get_pixmap().samples == reopened[0].get_pixmap().samples


@pytest.mark.skipif(os.name != "nt", reason="Windows font inventory")
def test_windows_chinese_collection_and_named_variable_face(tmp_path):
    result = font_catalogue()
    assert result["faces"]
    chinese = next((face for face in result["faces"]
                   if face["family"] == "Microsoft JhengHei" and face["style"] == "Regular"), None)
    if chinese is None:
        chinese = inspect_font_file(asset_root() / "fonts/NotoSansCJKhk-Regular.otf")[0]
    exact = export_face(chinese, tmp_path / "chinese")
    raw = render_preview(Template(elements=[Element(value="\u7530",
                         font=FontSpec(family=exact["family"], file=exact["file"]))]), {})
    with fitz.open(stream=raw, filetype="pdf") as doc:
        assert "\u7530" in doc[0].get_text()
    variable = next((face for face in result["faces"] if face["axes"]), None)
    if variable is None:
        pytest.skip("No named variable font installed in this Windows CI image")
    exact = export_face(variable, tmp_path / "variable")
    with TTFont(exact["file"]) as font:
        assert "fvar" not in font
    assert inspect_font_file(exact["file"])[0]["style"] == variable["style"]
    invalid = {**variable, "axes": {next(iter(variable["axes"])): float("nan")}}
    with pytest.raises(CompositionError, match="Invalid variable font axis"):
        export_face(invalid, tmp_path / "invalid")


def test_font_embedding_restriction_is_not_bypassed(tmp_path):
    source = asset_root() / "fonts/NotoSans-Regular.ttf"
    if not source.exists():
        pytest.skip("Prepared fonts required")
    restricted = tmp_path / "restricted.ttf"
    with TTFont(source) as font:
        font["OS/2"].fsType = 2
        font.save(restricted)
    face = inspect_font_file(restricted)[0]
    assert not face["usable"]
    with pytest.raises(CompositionError, match="does not permit"):
        export_face(face, tmp_path / "export")
