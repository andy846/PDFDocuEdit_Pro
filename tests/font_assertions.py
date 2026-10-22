"""Assert exact embedded faces, independent of MuPDF's display-name spelling."""
from io import BytesIO

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from composition.engine.fonts import resolve_font
from composition.template.model import FontSpec


def assert_span_face(page, span, family):
    path = resolve_font(FontSpec(family=family))
    with TTFont(path, lazy=True) as metadata:
        # 1.26 writes the PostScript name; 2.0 writes the full face name.
        labels = {metadata["name"].getDebugName(i) for i in (4, 6)}
        labels.add(metadata["name"].getDebugName(1) + " " + metadata["name"].getDebugName(2))
        assert span["font"] in labels
        for reference in page.get_fonts():
            data = page.parent.extract_font(reference[0])[3]
            if not data:
                continue
            with TTFont(BytesIO(data)) as embedded:
                embedded_labels = {embedded["name"].getDebugName(i) for i in (4, 6)}
                embedded_labels.add(embedded["name"].getDebugName(1) + " " + embedded["name"].getDebugName(2))
                if not embedded_labels & labels:
                    continue
                source_map = metadata.getBestCmap()
                # PDF subsets need not retain a cmap. Texttrace resolves the
                # PDF character mapping to the glyph ID actually rendered.
                target_map = {char[0]: char[1] for trace in page.get_texttrace()
                              if trace["font"] == span["font"] for char in trace["chars"]}
                for char in set(span["text"]) - set(" \r\n\t"):
                    code = ord(char)
                    assert code in source_map and code in target_map
                    shapes = []
                    names = (source_map[code], embedded.getGlyphOrder()[target_map[code]])
                    for face, name in zip((metadata, embedded), names, strict=True):
                        glyphs = face.getGlyphSet()
                        pen = DecomposingRecordingPen(glyphs)
                        glyphs[name].draw(pen)
                        shapes.append(pen.value)
                    assert shapes[0] == shapes[1], "Subset glyph outlines must match the selected font"
                return
    raise AssertionError("The selected font face must be embedded")
