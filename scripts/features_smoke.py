"""Windows native/frozen acceptance harness using generated, isolated PDFs."""
import json
import sys
import time
import traceback
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fitz
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from core.forms import apply_values, enumerate_fields
from core.viewer import PDFViewer
from dialogs.comparison_dialog import ComparisonDialog
from dialogs.form_dialog import FormDialog


def check(condition, message):
    # PyInstaller may optimize away assert statements, including their calls.
    if not condition:
        raise RuntimeError("Acceptance failed: " + message)


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(output / 'settings'))
    app = QApplication(['Feature acceptance'])
    app.setOrganizationName('PDFDocuEdit-QA')
    app.setApplicationName('Features-QA')
    path = output / 'form.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=620)
        page.insert_text((40, 48), 'Customer order', fontsize=22)
        for index, (name, value) in enumerate((('Customer', 'Original'), ('Quantity', '2'), ('Price', '30'), ('Total', '60'))):
            top = 100 + index * 80
            page.insert_text((40, top), name)
            widget = fitz.Widget()
            widget.field_name, widget.field_value = (name, value)
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.rect = fitz.Rect(40, top + 10, 420, top + 43)
            widget.border_color = (0.5, 0.6, 0.7)
            widget.border_width = 1
            if name == 'Total':
                widget.script_calc = 'event.value = this.getField("Quantity").value * this.getField("Price").value;'
                widget.field_flags = 1
            page.add_widget(widget)
        doc.save(path)
        data = doc.tobytes()
    window = PDFViewer()
    window.settings.set('animations_enabled', False)
    window.show()
    window.load_file(str(path))
    form = FormDialog(data, window)
    form.show()
    form._editor.setPlainText('中文客戶 Customer')
    check(form.update_preview(), 'form.update_preview()')
    form.staged['Quantity'] = '4'
    check(form.update_preview(), 'form.update_preview()')
    check(enumerate_fields(form.preview)[3].value == '120', "enumerate_fields(form.preview)[3].value == '120'")
    form.canvas.fit_page()
    app.processEvents()
    form.canvas.wait_for_renders()
    app.processEvents()
    form.grab().save(str(output / 'form.png'))
    with window._page_transaction('Form acceptance') as allowed:
        check(allowed, 'allowed')
        apply_values(window.engine.document, form.staged)
        window.engine.mark_modified()
    window._after_page_count_change()
    changed = window.engine.document.tobytes()
    check(enumerate_fields(window.engine.document)[0].value == '中文客戶 Customer', 'Unicode applied value')
    check('中文客戶' in window.engine.document[0].get_text(), 'Unicode rendered appearance')
    check(enumerate_fields(window.engine.document)[3].value == '120', "enumerate_fields(window.engine.document)[3].value == '120'")
    window._undo()
    check(enumerate_fields(window.engine.document)[3].value == '60', "enumerate_fields(window.engine.document)[3].value == '60'")
    window._redo()
    check(enumerate_fields(window.engine.document)[3].value == '120', "enumerate_fields(window.engine.document)[3].value == '120'")
    form.release()
    form.close()
    comparison = ComparisonDialog(('Before', lambda: data, lambda: 1), [('After', lambda: changed, lambda: 1)], window)
    comparison.show()
    comparison.start_comparison()
    deadline = time.monotonic() + 30
    while comparison._task is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(comparison._task is None, 'comparison._task is None')
    check(comparison.results[0].status == 'Modified', "comparison.results[0].status == 'Modified'")
    for canvas in comparison.canvases:
        canvas.fit_page()
        canvas.wait_for_renders()
    app.processEvents()
    comparison.grab().save(str(output / 'comparison.png'))
    comparison.close()
    window._confirm_discard_changes = lambda: True
    window.close()
    (output / 'result.json').write_text(json.dumps({'passed': True, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': ['Unicode form preview', 'calculation', 'Apply', 'Undo', 'Redo', 'asynchronous comparison', 'native UI render']}, indent=2), encoding='utf-8')
if __name__ == '__main__':
    target = Path(sys.argv[1]).resolve()
    try:
        run(target)
    except Exception:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
