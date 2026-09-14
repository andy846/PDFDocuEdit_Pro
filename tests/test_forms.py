import fitz
import pytest

from core.forms import FormError, apply_values, enumerate_fields, parse_calculation, validate_values


def form_pdf():
    doc = fitz.open()
    page = doc.new_page()
    for index, (name, value, script) in enumerate((('A', '2', None), ('B', '3', None),
            ('Total', '', 'AFSimple_Calculate("SUM", new Array("A", "B"));'))):
        widget = fitz.Widget()
        widget.field_name = name
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = value
        widget.script_calc = script
        widget.rect = fitz.Rect(20, 30 + index * 40, 250, 60 + index * 40)
        page.add_widget(widget)
    return doc


def test_calculation_and_save_reopen():
    with form_pdf() as doc:
        apply_values(doc, {'A': '7'})
        with fitz.open(stream=doc.tobytes(), filetype='pdf') as reopened:
            values = {f.name: f.value for f in enumerate_fields(reopened)}
            assert values == {'A': '7', 'B': '3', 'Total': '10'}
            assert reopened[0].first_widget is not None


@pytest.mark.parametrize('script', [
    'event.value = __import__("os").system("echo bad")',
    'event.value = this.getField("A").value ** 9999;',
    'event.value = unknown + 3;',
])
def test_no_arbitrary_execution(script):
    with pytest.raises(FormError):
        parse_calculation(script)


def test_dependency_and_validation_failures():
    with form_pdf() as doc:
        fields = enumerate_fields(doc)
        fields[2].calculation = 'event.value = this.getField("A").value / this.getField("B").value;'
        assert validate_values(fields, {'A': '9'})[0]['Total'] == '3'
        with pytest.raises(FormError, match='zero'):
            validate_values(fields, {'B': '0'})
        with pytest.raises(FormError, match='numeric'):
            validate_values(fields, {'B': 'hello'})
        fields[0].calculation = 'event.value = this.getField("Total").value;'
        with pytest.raises(FormError, match='Circular'):
            validate_values(fields, {})
        fields[0].calculation = 'event.value = this.getField("Missing").value;'
        with pytest.raises(FormError, match='missing'):
            validate_values(fields, {})


def test_unicode_appearance_retains_editable_value():
    with form_pdf() as doc:
        # No calculation can consume this text field.
        page = doc[0]
        widget = page.load_widget(enumerate_fields(doc)[2].widgets[0].xref)
        widget.script_calc = None
        widget.update()
        apply_values(doc, {'A': '中文測試 English'})
        with fitz.open(stream=doc.tobytes(), filetype='pdf') as saved:
            assert enumerate_fields(saved)[0].value == '中文測試 English'
            assert '中文測試' in saved[0].get_text()
            assert saved[0].get_pixmap().width > 0


def test_dialog_preview_cancel_is_private():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from dialogs.form_dialog import FormDialog
    with form_pdf() as doc:
        data = doc.tobytes(no_new_id=True)
        dialog = FormDialog(data)
        app.processEvents()
        try:
            dialog._editor.setPlainText('10')
            assert dialog.update_preview()
            assert enumerate_fields(dialog.preview)[2].value == '13'
            assert enumerate_fields(doc)[0].value == '2'
            dialog.reject()
            assert doc.tobytes(no_new_id=True) == data
        finally:
            dialog.release()


def test_options_and_signature():
    with fitz.open() as doc:
        page = doc.new_page()
        for index, kind in enumerate((fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_LISTBOX,
                                      fitz.PDF_WIDGET_TYPE_SIGNATURE)):
            widget = fitz.Widget()
            widget.field_name = f'field{index}'
            widget.field_type = kind
            widget.rect = fitz.Rect(20, 20 + 80 * index, 200, 80 + 80 * index)
            if kind == fitz.PDF_WIDGET_TYPE_LISTBOX:
                widget.field_flags = 1 << 21
                widget.choice_values = [('export1', 'Label one'), ('export2', 'Label two')]
            page.add_widget(widget)
        fields = enumerate_fields(doc)
        state = next(s for s in fields[0].widgets[0].states if s != 'Off')
        image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
        image.clear_with(50)
        apply_values(doc, {'field0': state, 'field1': ['export1', 'export2']}, {'field2': image.tobytes('png')})
        saved = enumerate_fields(doc)
        assert saved[0].value == state
        assert saved[1].value == ['export1', 'export2']
        assert not saved[2].signed
        assert doc.xref_get_key(saved[2].widgets[0].xref, 'V')[0] == 'null'


def test_form_transaction_restores_after_partial_failure(tmp_path):
    from core.pdf_engine import PdfEngine, PdfEngineError
    from core.undo import UndoStack
    path = tmp_path / 'form.pdf'
    with form_pdf() as doc:
        doc.save(path)
    stack = UndoStack()
    engine = PdfEngine(on_commit=stack.push_bytes)
    engine.open(path)
    try:
        with engine.mutation_transaction('Form'):
            apply_values(engine.document, {'A': '9'})
            engine.mark_modified()
        assert stack.undo_descriptions() == ['Form']
        with pytest.raises(PdfEngineError):
            with engine.mutation_transaction('Fail'):
                apply_values(engine.document, {'A': '20'})
                raise OSError('injected after mutation')
        assert enumerate_fields(engine.document)[0].value == '9'
        assert stack.undo_descriptions() == ['Form']
    finally:
        engine.close()
        stack.clear()


def test_clear_text_and_empty_multiselect():
    with form_pdf() as doc:
        apply_values(doc, {"A": ""})
        assert enumerate_fields(doc)[0].value == ""
        assert enumerate_fields(doc)[2].value == "3"
    with fitz.open() as doc:
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_name = "multi"
        widget.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
        widget.field_flags = 1 << 21
        widget.choice_values = ["a", "b"]
        widget.rect = fitz.Rect(20, 20, 200, 100)
        page.add_widget(widget)
        apply_values(doc, {"multi": ["a"]})
        apply_values(doc, {"multi": []})
        assert enumerate_fields(doc)[0].value == []


def test_radio_export_states_and_clear():
    with fitz.open() as doc:
        page = doc.new_page()
        for index in range(2):
            widget = fitz.Widget()
            widget.field_name = f"button{index}"
            widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
            widget.rect = fitz.Rect(20 + index * 50, 20, 40 + index * 50, 40)
            page.add_widget(widget)
        refs = [w.xref for w in page.widgets()]
        for xref, name in zip(refs, ["First", "Second"], strict=True):
            appearance = doc.xref_get_key(xref, "AP/N")[1].replace("/Yes", f"/{name}")
            doc.xref_set_key(xref, "AP/N", appearance)
            doc.xref_set_key(xref, "Ff", "32768")
        group = doc.get_new_xref()
        kids = " ".join(f"{xref} 0 R" for xref in refs)
        doc.update_object(group, f"<< /FT /Btn /Ff 32768 /T (Choice) /Kids [{kids}] >>")
        for xref in refs:
            doc.xref_set_key(xref, "Parent", f"{group} 0 R")
            doc.xref_set_key(xref, "T", "null")
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm/Fields", f"[{group} 0 R]")
        apply_values(doc, {"Choice": "Second"})
        assert enumerate_fields(doc)[0].value == "Second"
        assert [doc.xref_get_key(x, "AS")[1] for x in refs] == ["/Off", "/Second"]
        apply_values(doc, {"Choice": "Off"})
        assert enumerate_fields(doc)[0].value == "Off"


def test_readonly_required_and_duplicate_widgets():
    with fitz.open() as doc:
        page = doc.new_page()
        for index in range(2):
            widget = fitz.Widget()
            widget.field_name = "Shared"
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(20, 20 + index * 50, 200, 50 + index * 50)
            widget.field_value = "Initial"
            page.add_widget(widget)
        apply_values(doc, {"Shared": "New"})
        assert [w.field_value for w in doc[0].widgets()] == ["New", "New"]
        fields = enumerate_fields(doc)
        fields[0].flags = 1
        with pytest.raises(FormError, match="cannot be edited"):
            validate_values(fields, {"Shared": "Blocked"})
        fields[0].flags = 2
        with pytest.raises(FormError, match="required"):
            validate_values(fields, {"Shared": ""})


def test_unsupported_calculation_does_not_feed_stale_values_to_dependents():
    with form_pdf() as doc:
        fields = enumerate_fields(doc)
        fields[0].calculation = "event.value = customBusinessRule();"
        values, warnings = validate_values(fields, {"B": "8"})
        assert values["Total"] == fields[2].value
        assert any("Total: depends on an unsupported" in warning for warning in warnings)
