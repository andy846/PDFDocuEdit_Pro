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
        stream.write("Name,Account,Scheme_Code,Balance\n")
        for index in range(100):
            stream.write(f"\u9673\u5c0f\u660e,{index:08},{'GS' if index % 2 == 0 else 'IS'},{20001 if index % 2 == 0 else 0}\n")
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
    # Bulk size changes retain different primary faces, values and repairs.
    from copy import deepcopy
    bulk_before = window.template.to_dict()
    window.canvas.select_ids([window.page.elements[0].id, window.page.elements[1].id])
    window.font_size_tool.setValue(12)
    window.font_size_tool.editingFinished.emit()
    expected = deepcopy(bulk_before)
    for element in expected["pages"][0]["elements"][:2]:
        element["font"]["size_pt"] = 12
    check(window.template.to_dict() == expected, "Bulk size changed unrelated formatting")
    window.focus_properties()
    window.properties_scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    wait(lambda: window.canvas.preview_item is not None)
    window.grab().save(str(output/"bulk-text-format.png"))
    window.undo.undo()
    check(window.template.to_dict() == bulk_before, "Bulk size Undo failed")
    window.canvas.select_ids([window.page.elements[1].id, window.page.elements[-1].id])
    window.properties.loading = True
    window.properties.font_family.setCurrentText("Arial")
    window.properties._set_styles("Arial")
    window.properties.font_style.setCurrentIndex(window.properties.font_style.findText("Bold"))
    window.properties.loading = False
    window.properties.font_style.activated.emit(window.properties.font_style.currentIndex())
    wait(lambda: not window.font_requests)
    for index in (1, 4):
        check(load_font(window.page.elements[index].font)[0].is_bold, "Bulk exact face failed")
        check(asdict(window.page.elements[index].font)["size_pt"] == bulk_before["pages"][0]["elements"][index]["font"]["size_pt"], "Bulk face changed individual size")
    check(asdict(window.page.elements[-1])["glyph_repairs"] == bulk_before["pages"][0]["elements"][-1]["glyph_repairs"], "Bulk face lost glyph repair")
    window.undo.undo()
    check(window.template.to_dict() == bulk_before, "Bulk exact face Undo failed")
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
    # Exercise real rule editor controls on the continuation page.
    from composition.designer.rules_dialog import RulesDialog

    def set_condition(group, field, operator="eq", kind="text", value="", row=0):
        group.setChecked(True)
        field_box, compare, data_type, target = (group.table.cellWidget(row, col) for col in range(4))
        field_box.setCurrentText(field)
        data_type.setCurrentIndex(data_type.findData(kind))
        compare.setCurrentIndex(compare.findData(operator))
        target.setText(value)

    fields = ["Name", "Account", "Scheme_Code", "Balance"]
    window.canvas.select_ids([window.page.elements[0].id])
    rules_dialog = RulesDialog(window.page.elements[0], fields, parent=window)
    set_condition(rules_dialog.variant, "Scheme_Code", value="GS")
    rules_dialog.alt_text.setPlainText("GS continuation: {{Account}}")
    rules_dialog.show()
    QApplication.processEvents()
    rules_dialog.grab().save(str(output/"rules-dialog.png"))
    rules_dialog.apply_rules()
    window.apply_object_rules(rules_dialog.choice)
    window.add_element("text", "GS-only message", x=20, y=80)
    rules_dialog = RulesDialog(window.page.elements[-1], fields, parent=window)
    set_condition(rules_dialog.visibility, "Scheme_Code", value="GS")
    rules_dialog.visibility.add_condition()
    set_condition(rules_dialog.visibility, "Balance", "gt", "number", "10000", row=1)
    rules_dialog.apply_rules()
    window.apply_object_rules(rules_dialog.choice)
    red, blue = output/"normal.png", output/"alternate.png"
    Image.new("RGB", (20, 20), "red").save(red)
    Image.new("RGB", (20, 20), "blue").save(blue)
    original_open_dialog = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = lambda *args, **kwargs: (str(red), "")
    try:
        window.add_element("image", x=20, y=115)
    finally:
        QFileDialog.getOpenFileName = original_open_dialog
    before, after = window.template.to_dict(), window.template.to_dict()
    after["pages"][1]["elements"][-1].update(image=str(red), width_mm=20, height_mm=20)
    window._commit(before, after, "Image rule demonstration", after["pages"][1]["elements"][-1]["id"])
    rules_dialog = RulesDialog(window.page.elements[-1], fields, parent=window)
    set_condition(rules_dialog.variant, "Scheme_Code", value="GS")
    rules_dialog.alt_image.setText(str(blue))
    rules_dialog.apply_rules()
    window.apply_object_rules(rules_dialog.choice)
    window.tabs.setCurrentIndex(2)
    wait(lambda: window.canvas.preview_item is not None)
    window.record.setValue(18)
    wait(lambda: window.canvas.preview_item is not None)
    check("1 hidden / 0 alternative" in window.preview_state.text(), "Record rule preview mismatch")
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
    check(len(loaded.pages[1].elements) == 3 and loaded.pages[1].elements[0].rules.alternative is not None, "Saved rules missing")
    check(Path(loaded.pages[1].elements[-1].rules.alternative.image).is_file(), "Saved alternative asset missing")
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
        check("GS continuation: 00000000" in doc[1].get_text(), "Alternative text/order mismatch")
        check("GS-only message" in doc[1].get_text() and "GS-only message" not in doc[3].get_text(), "Conditional visibility failed")
        check("Continuation: 00000001" in doc[3].get_text(), "Normal content failed")
        for page_index, colour in [(1, (0, 0, 255)), (3, (255, 0, 0))]:
            pix = doc[page_index].get_pixmap(alpha=False)
            rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            check(rendered.getpixel((85, 354)) == colour, "Alternative image failed")
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
    check(report["rule_summary"] == {"configured_objects": 3, "records_checked": 100,
          "hidden_occurrences": 50, "alternate_occurrences": 100, "complete": True}, "Rule reconciliation failed")
    check(Path(report["glyph_repair_report"]).is_file(), "Repair audit CSV missing")
    window.grab().save(str(output/"production.png"))
    # Existing editor still opens PDFs while the new workspace exists.
    editor.load_file(str(background))
    wait(lambda: editor.engine.is_loaded())
    check("Company Statement" in editor.engine.document[0].get_text(), "Existing editor regressed")
    # Exercise the real sequence dialog, virtual records and the frozen worker path.
    from composition.designer.sequence_dialog import SequenceDialog
    from composition.designer.workspace import CompositionWindow
    seq_window = CompositionWindow()
    seq_window.show()
    seq_dialog = SequenceDialog(seq_window.template, parent=seq_window)
    seq_dialog.show()
    seq_dialog.mode.setCurrentIndex(1)
    seq_dialog.quantity.setValue(100)
    seq_dialog.table.item(0, 0).setText("Ticket")
    seq_dialog.table.item(0, 3).setText("5")
    seq_dialog.table.item(0, 4).setText("T-")
    seq_dialog.add_sequence()
    seq_dialog.table.item(1, 0).setText("PageSeq")
    seq_dialog.table.cellWidget(1, 6).setCurrentIndex(1)
    app.processEvents()
    seq_dialog.grab().save(str(output/"running-sequences.png"))
    seq_dialog.accept()
    choice = seq_dialog.choice
    check(choice is not None, "Sequence dialog did not produce settings")
    check(seq_window.apply_sequences(choice.sequences, choice.record_mode, choice.generated_count), "Sequence commit failed")
    seq_window.undo.undo()
    check(seq_window.record_count == 0, "Sequence Undo failed")
    seq_window.undo.redo()
    seq_window.add_element("text", "{{Ticket}} / {{PageSeq}}", x=20, y=30)
    seq_window.add_element("code128", "{{Ticket}}", x=20, y=70)
    seq_window.add_element("qr", "{{Ticket}}", x=140, y=70)
    seq_window.add_template_page(duplicate=True)
    seq_window.tabs.setCurrentIndex(2)
    seq_window.record.setValue(100)
    wait(lambda: seq_window.canvas.preview_item is not None and "Record 100" in seq_window.preview_state.text())
    seq_window.grab().save(str(output/"sequence-preview.png"))
    from composition.template.serializer import save_project
    seq_project = save_project(seq_window.template, output/"tickets.pdcx")
    seq_window.start_production(str(output/"tickets-output"))
    wait(lambda: seq_window.production_worker is None, 90)
    check(bool(seq_window.last_output), seq_window.production_summary.toPlainText())
    with fitz.open(seq_window.last_output) as pdf:
        check(pdf.page_count == 200, "Virtual production reconciliation failed")
        check("T-00001 / 000001" in pdf[0].get_text(), "First sequence wrong")
        check("T-00100 / 000200" in pdf[-1].get_text(), "Last/page sequence wrong")
        pix = pdf[-1].get_pixmap(matrix=fitz.Matrix(3,3), alpha=False)
        image = Image.frombytes("RGB", (pix.width,pix.height), pix.samples)
        decoded = decode(image)
        check({item.type for item in decoded} >= {"CODE128", "QRCODE"}, "Sequence barcode decoding failed")
        check(all(item.data == b"T-00100" for item in decoded), "Barcode sequence value wrong")
    seq_window.undo.setClean()
    seq_window.open_project(path=str(seq_project))
    check(seq_window.record_count == 100 and seq_window.import_worker is None, "Virtual project reopened with wrong source")
    seq_window.undo.setClean()
    seq_window.close()
    wait(lambda: not seq_window.workers)
    summary = {"passed":True,"frozen":bool(getattr(sys,"frozen",False)),
               "scale":os.environ.get("QT_SCALE_FACTOR","1"), "records":100, "pages":200,
               "pdf":window.last_output, "event_loop_ticks":len(ticks),
               "checks":["Welcome entry","PDF background","CSV import","Chinese preview","exact fonts","Windows font family/style selection",
                         "Code128 decoding","QR decoding","save and reopen","reconciliation",
                         "background production","existing editor open", "per-glyph repair preserves primary face", "glyph repair audit", "multi-page template/save/preview", "page reorder and undo", "independent page sizes", "record/page reconciliation", "typed variable drafts", "compact/wide inspector", "field filtering", "rules editor", "conditional visibility", "alternative text/image", "rules save/reopen", "rule reconciliation", "bulk text size", "bulk exact Windows face", "bulk one-command Undo", "bulk glyph repair preservation", "running sequence dialog", "virtual records", "sequence Undo", "per-record/page sequence", "sequence QR/Code128 decoding", "generated project reopen"]}
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
