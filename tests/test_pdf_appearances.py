import fitz
import numpy as np
import pytest

from core.pdf_operations.appearances import AppearanceError, flatten_page


def pixels(page):
    return np.frombuffer(page.get_pixmap(matrix=fitz.Matrix(2, 2)).samples, dtype=np.uint8).astype(int)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_selected_page_preserves_visible_appearance_text_and_unselected_annotations(rotation):
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=400, height=500)
        page.insert_text((50, 70), "Searchable original text")
        page.add_freetext_annot((40, 100, 240, 160), "Visible value", fontsize=15)
        rect = page.add_rect_annot((50, 200, 140, 260))
        rect.set_colors(stroke=(1, 0, 0), fill=(0, 1, 0))
        rect.set_opacity(0.4)
        rect.update()
        page.set_cropbox(fitz.Rect(20, 20, 370, 480))
        page.set_rotation(rotation)
    before = pixels(doc[0])
    assert flatten_page(doc, 0) == 2
    with fitz.open(stream=doc.tobytes(garbage=4), filetype="pdf") as output:
        after = pixels(output[0])
        assert np.max(np.abs(before - after)) <= 2
        assert not list(output[0].annots() or [])
        assert len(list(output[1].annots() or [])) == 2
        assert "Searchable original text" in output[0].get_text()
        assert "Visible value" in output[0].get_text()
        assert output[0].rotation == rotation


@pytest.mark.parametrize("kind", [fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX,
                                  fitz.PDF_WIDGET_TYPE_RADIOBUTTON, fitz.PDF_WIDGET_TYPE_COMBOBOX,
                                  fitz.PDF_WIDGET_TYPE_LISTBOX])
def test_form_values_and_unselected_widgets_remain(kind):
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_name = "Customer" + str(i)
        widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX if kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON else kind
        widget.rect = fitz.Rect(20, 20, 180, 50)
        if kind in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
            widget.choice_values = ["John", "Mary"]
        widget.field_value = "John" if kind in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX) else "Yes"
        added = page.add_widget(widget)
        if kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            # MuPDF's new radio-widget helper rejects xref=0. Encode the
            # standard radio flag on an existing Btn widget instead.
            doc.xref_set_key(added.xref, "Ff", "32768")
    before = pixels(doc[0])
    assert flatten_page(doc, 0, annotations=False, widgets=True) == 1
    assert np.max(np.abs(before - pixels(doc[0]))) <= 2
    assert not list(doc[0].widgets() or [])
    assert len(list(doc[1].widgets() or [])) == 1


def test_redaction_is_never_a_flatten_substitute():
    doc = fitz.open()
    page = doc.new_page()
    page.add_redact_annot((20, 20, 100, 100))
    with pytest.raises(AppearanceError, match="redaction"):
        flatten_page(doc, 0)


@pytest.mark.parametrize("kind", ["highlight", "underline", "strikeout", "ink", "stamp", "circle", "line"])
def test_annotation_types_preserve_normal_appearance(kind):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), "Searchable marked text")
        selection = page.search_for("marked")
        if kind in ("highlight", "underline", "strikeout"):
            getattr(page, "add_" + kind + "_annot")(selection)
        elif kind == "ink":
            page.add_ink_annot([[(40, 100), (70, 120), (90, 110)]])
        elif kind == "stamp":
            page.add_stamp_annot((40, 100, 240, 180))
        elif kind == "circle":
            page.add_circle_annot((40, 100, 150, 200))
        else:
            page.add_line_annot((40, 100), (150, 200))
        before = pixels(page)
        assert flatten_page(doc, 0) == 1
        assert np.max(np.abs(before - pixels(doc[0]))) <= 3
        assert "Searchable marked text" in doc[0].get_text()
        assert not list(doc[0].annots() or [])
