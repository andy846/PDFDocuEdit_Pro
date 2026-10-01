"""Opt-in native/frozen Document Designer acceptance; generated data only."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The same executable must also serve the workspace's headless subprocesses.
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--composition-worker":
    from composition.worker import main as worker_main
    raise SystemExit(worker_main(sys.argv[2:]))

import fitz
from PIL import Image
from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QPushButton

from composition.engine.assets import asset_root
from composition.template.model import DataConfig
from composition.template.serializer import load_project
from core.settings import SettingsManager


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def wait(predicate, seconds=40):
    deadline = time.monotonic()+seconds
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(10)
    check(predicate(), "Timeout waiting for composition result")


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(output/"settings"))
    app = QApplication.instance() or QApplication(["Composition acceptance"])
    app.setOrganizationName("PDFDocuEdit-QA")
    app.setApplicationName("Composition-QA")
    QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSans-Regular.ttf"))
    QFontDatabase.addApplicationFont(str(asset_root()/"fonts"/"NotoSansCJKhk-Regular.otf"))
    app.setFont(QFont("Noto Sans", 9))
    import core.viewer as viewer_module
    viewer_module.SettingsManager = lambda: SettingsManager(output/"settings.json")
    editor = viewer_module.PDFViewer()
    editor.settings.set("animations_enabled", False)
    editor.show()
    check(any(button.text() == "Document Designer" for button in editor.findChildren(QPushButton)),
          "Welcome composition entry missing")
    editor._welcome_tool("composition")
    window = editor._composition_window
    check(window is not None, "Composition workspace did not launch")
    background = output/"company.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((55, 55), "Company Statement", fontsize=18)
        page.draw_line((55, 70), (530, 70), color=(.2, .4, .7))
        doc.save(background)
    source = output/"source.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        stream.write("Name,Account\n")
        for index in range(100):
            stream.write(f"\u9673\u5c0f\u660e,{index:08}\n")
    window._worker({"task":"background","source":str(background),"page":0,
                    "target":str(window.directory/"company.pdf")}, window._background_ready)
    wait(lambda: bool(window.template.background))
    window.add_field("Name", 20, 65)
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][0]["elements"][-1]["font"]["family"] = "Noto Sans CJK HK"
    window._commit(before, after, "CJK output font", after["pages"][0]["elements"][-1]["id"])
    window.add_element("text", "Account: {{Account}}", x=20, y=95)
    window.add_element("code128", "{{Account}}", x=20, y=125)
    window.add_element("qr", "{{Account}}", x=140, y=125)
    window._start_import(DataConfig(path=str(source)))
    wait(lambda: window.import_worker is None)
    check(window.record_count == 100, "Import count mismatch")
    wait(lambda: "Arial" in window.properties.catalogue)
    window.canvas.select_ids([window.template.elements[1].id])
    window.properties.font_family.setCurrentIndex(window.properties.font_family.findText("Arial"))
    wait(lambda: not window.font_requests and bool(window.template.elements[1].font.file))
    bold = window.properties.font_style.findText("Bold")
    check(bold >= 0, "Windows bold face not listed")
    window.properties.font_style.setCurrentIndex(bold)
    window.properties._style_chosen()
    wait(lambda: not window.font_requests)
    from composition.engine.fonts import load_font
    check(load_font(window.template.elements[1].font)[0].is_bold, "Windows exact bold face not selected")
    # Configure the repair through the actual dialog controls, retaining the primary face.
    from dataclasses import asdict

    from composition.designer.glyph_dialog import GlyphRepairDialog
    window.add_element("text", "Client face: \u7530, only this glyph repaired", x=20, y=150)
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][0]["elements"][-1].update(height_mm=20, width_mm=170, vertical_align="center")
    window._commit(before, after, "Repair demonstration box", after["pages"][0]["elements"][-1]["id"])
    primary = asdict(window.template.elements[-1].font)
    dialog = GlyphRepairDialog(window.template.elements[-1], window.properties.catalogue, "U+7530", window)
    dialog.family.setCurrentText("Noto Sans CJK HK")
    dialog.show()
    QApplication.processEvents()
    dialog.grab().save(str(output/"glyph-repair-dialog.png"))
    dialog._apply()
    window._request_font(dialog.choice)
    wait(lambda: not window.font_requests)
    check(asdict(window.template.elements[-1].font) == primary, "Repair changed primary font")
    check("U+7530" in window.template.elements[-1].glyph_repairs, "Repair setting not applied")
    window.actions["page_add"].trigger()
    check(window.page_index == 1, "Add template page did not select new page")
    window.add_element("text", "Continuation: {{Account}}", x=20, y=35)
    window.properties.content.setFocus()
    window.properties.content.selectAll()
    QTest.keyClicks(window.properties.content, "Continuation: {{Account")
    check(window.content_invalid and not window.actions["generate"].isEnabled(),
          "Unfinished field reference must remain editable and block stale output")
    QTest.keyClicks(window.properties.content, "}}")
    check(not window.content_invalid and window.page.elements[0].value == "Continuation: {{Account}}",
          "Typed field reference lost its draft")
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][1].update(width_mm=148, height_mm=210, name="Continuation")
    window._commit(before, after, "A5 continuation")
    window.actions["page_up"].trigger()
    check(window.page_index == 0, "Page reorder failed")
    window.undo.undo()
    check(window.page_index == 1, "Page reorder undo failed")
    window.tabs.setCurrentIndex(2)
    wait(lambda: window.canvas.preview_item is not None)
    window.record.setValue(18)
    wait(lambda: window.canvas.preview_item is not None)
    window.grab().save(str(output/"preview-page-two.png"))
    window.page_combo.setCurrentIndex(0)
    window.resize(960, 640)
    window.tabs.setCurrentIndex(2)
    wait(lambda: window.canvas.preview_item is not None)
    window.record.setValue(18)
    wait(lambda: window.canvas.preview_item is not None)
    window.canvas.fit_page()
    window.grab().save(str(output/"preview.png"))
    for theme in ("light", "dark"):
        editor.apply_theme(theme)
        window.tabs.setCurrentIndex(1)
        wait(lambda: window.canvas.preview_item is not None)
        window.canvas.select_ids([window.template.elements[0].id])
        check(window.properties.element is not None, "Selected object properties missing")
        window._adjust_inspector()
        check(window.compact_inspector, "Compact inspector missing at 960 px")
        window.focus_properties()
        app.processEvents()
        check(window.properties.isVisible() and window.properties.content.width() > 30, "Compact properties were not laid out")
        window.grab().save(str(output/f"designer-{theme}.png"))
    window.resize(1240, 820)
    window._adjust_inspector()
    check(not window.compact_inspector, "Wide inspector did not restore")
    app.processEvents()
    check(window.properties_scroll.width() >= 260 and window.properties.isVisible(), "Wide properties were not laid out")
    window.grab().save(str(output/"designer-wide.png"))
    window.resize(960, 640)
    window._adjust_inspector()
    window.field_filter.setText("account")
    check(window.fields.item(0).isHidden() and not window.fields.item(1).isHidden(), "Field filter failed")
    window.field_filter.clear()
    project = output/"statement.pdcx"
    original_save_dialog = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(project), "")
    try:
        check(window.save_project(), "Project save failed")
    finally:
        QFileDialog.getSaveFileName = original_save_dialog
    loaded = load_project(project)
    check(len(loaded.pages) == 2 and len(loaded.elements) == 5, "Saved template lost pages/objects")
    check(Path(loaded.background).is_file(), "Saved background missing")
    check("U+7530" in loaded.elements[-1].glyph_repairs, "Saved glyph repair missing")
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start(10)
    window.start_production(str(output/"production"))
    wait(lambda: window.production_worker is None, 90)
    timer.stop()
    check(bool(ticks), "GUI event loop stopped during production")
    check(bool(window.last_output), window.production_summary.toPlainText())
    with fitz.open(window.last_output) as doc:
        check(doc.page_count == 200, "Production page count mismatch")
        check("Continuation: 00000000" in doc[1].get_text(), "Record/page order mismatch")
        check(abs(doc[1].rect.width-148*72/25.4) < .01, "Independent page size lost")
        check("\u9673\u5c0f\u660e" in doc[0].get_text(), "Chinese output text missing")
        check("00000099" in doc[-1].get_text(), "Record order mismatch")
        check("Company Statement" in doc[0].get_text(), "Background text missing")
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(3,3),alpha=False)
        image = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
        from pyzbar.pyzbar import decode
        check({item.type for item in decode(image)} >= {"CODE128","QRCODE"}, "Barcode decoding failed")
    import json as json_report
    report = json_report.loads((Path(window.last_output).parent/"job.json").read_text(encoding="utf-8"))
    check(report["repaired_glyphs"] == report["repaired_records"] == 100, "Repair reconciliation missing")
    check(Path(report["glyph_repair_report"]).is_file(), "Repair audit CSV missing")
    window.grab().save(str(output/"production.png"))
    # Existing editor still opens PDFs while the new workspace exists.
    editor.load_file(str(background))
    wait(lambda: editor.engine.is_loaded())
    check("Company Statement" in editor.engine.document[0].get_text(), "Existing editor regressed")
    summary = {"passed":True,"frozen":bool(getattr(sys,"frozen",False)),
               "scale":os.environ.get("QT_SCALE_FACTOR","1"), "records":100, "pages":200,
               "pdf":window.last_output, "event_loop_ticks":len(ticks),
               "checks":["Welcome entry","PDF background","CSV import","Chinese preview","exact fonts","Windows font family/style selection",
                         "Code128 decoding","QR decoding","save and reopen","reconciliation",
                         "background production","existing editor open", "per-glyph repair preserves primary face", "glyph repair audit", "multi-page template/save/preview", "page reorder and undo", "independent page sizes", "record/page reconciliation", "typed variable drafts", "compact/wide inspector", "field filtering"]}
    window.undo.setClean()
    window.close()
    wait(lambda: not window.workers)
    editor.close()
    (output/"result.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    output = Path(args[0]).resolve()
    try:
        run(output)
        return 0
    except Exception:
        output.mkdir(parents=True,exist_ok=True)
        (output/"failure.txt").write_text(traceback.format_exc(),encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
