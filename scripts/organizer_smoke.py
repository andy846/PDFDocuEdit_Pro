"""Native Qt Organizer acceptance harness; can be frozen with the application spec.

Run with one output directory argument. Uses generated PDFs and isolated settings.
This is a QA entry point, never a release application entry point.
"""
from __future__ import annotations

import json
import sys
import traceback
import uuid
from pathlib import Path
from time import monotonic

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from core.page_plan import PagePlanEntry, PlanReader, export_plan, interleave_entries
from core.viewer import PDFViewer
from dialogs.document_dialogs import VisualOrganizerDialog
from dialogs.organizer_tools import BlankPagesDialog, CropDialog, SplitPlanDialog, run_job


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(output / "settings"))
    app = QApplication.instance() or QApplication(["Organizer QA"])
    app.setOrganizationName("PDFDocuEdit-QA")
    app.setApplicationName("Organizer-QA")
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Segoe UI", 10))
    source, external = output / "A.pdf", output / "B.pdf"
    for target, count, label in ((source, 4, "A"), (external, 3, "B")):
        with fitz.open() as document:
            for i in range(count):
                page = document.new_page(width=400 + i * 20, height=600)
                page.insert_text((100, 200), f"{label}{i + 1}", fontsize=26)
                page.draw_rect(fitz.Rect(70, 90, 160, 140), fill=(.2, .5, .8))
                visible = document.add_ocg("Same name", on=True)
                hidden = document.add_ocg("Same name", on=False)
                page.insert_text((100, 250), "Visible layer", oc=visible)
                page.insert_text((100, 280), "Hidden layer", oc=hidden)
            document.save(target)
    window = PDFViewer()
    window.show()
    window.load_file(str(source))
    deadline = monotonic() + 30
    while not window.engine.is_loaded() and monotonic() < deadline:
        QTest.qWait(10)
    if not window.engine.is_loaded():
        raise RuntimeError("Asynchronous document opening did not finish")
    app.processEvents()
    failures = []
    final = []
    exported = []
    expected = []

    def button(dialog, label):
        matches = [b for b in dialog.findChildren(QPushButton) if b.text() == label]
        if len(matches) != 1:
            raise AssertionError(f"Missing/ambiguous button: {label}")
        QTest.mouseClick(matches[0], Qt.MouseButton.LeftButton)
        app.processEvents()

    def interact():
        dialog = next(w for w in app.topLevelWidgets() if isinstance(w, VisualOrganizerDialog) and w.isVisible())
        try:
            dialog.selection_input.setFocus()
            QTest.keyClicks(dialog.selection_input, "odd")
            QTest.keyClick(dialog.selection_input, Qt.Key.Key_Return)
            assert dialog.pages.selected_positions() == [0, 2]
            button(dialog, "Reverse")
            assert dialog.pages.order() == [2, 1, 0, 3]
            button(dialog, "Duplicate")
            button(dialog, "Rotate right")
            rotated = dialog.pages.page_plan()
            button(dialog, "Undo plan")
            button(dialog, "Redo plan")
            assert dialog.pages.page_plan() == rotated
            crop = CropDialog(rotated, dialog.pages.selected_positions(), dialog.pages.reader, dialog)
            crop.show()
            app.processEvents()
            rect = crop.canvas.image_rect()
            start = rect.topLeft() + (rect.bottomRight() - rect.topLeft()) * .08
            end = rect.topLeft() + (rect.bottomRight() - rect.topLeft()) * .92
            QTest.mousePress(crop.canvas, Qt.MouseButton.LeftButton, pos=start.toPoint())
            QTest.mouseRelease(crop.canvas, Qt.MouseButton.LeftButton, pos=end.toPoint())
            assert crop.inputs[0].value() > 0
            crop.inputs[0].setValue(5)
            assert crop.canvas.margins[0] == 5
            crop.grab().save(str(output / "crop.png"))
            crop._apply()
            dialog.pages.set_plan(crop.plan)
            snap, rotations = run_job(dialog, "Snapshot B", lambda **kw: dialog.sources.snapshot(str(external), **kw))
            b = [PagePlanEntry(uuid.uuid4().hex, "external", i, snap, rotation, source_label="B.pdf") for i, rotation in enumerate(rotations)]
            plan = interleave_entries(dialog.pages.page_plan(), b, reverse_b=True, pad=True, size_of=dialog.pages.reader.size)
            dialog.pages.set_plan(plan)
            def confirm_blank():
                blank = app.activeModalWidget()
                try:
                    assert isinstance(blank, BlankPagesDialog)
                    assert callable(blank.width) and callable(blank.height)
                    blank.paper.setCurrentIndex(3)
                    blank.width_mm.setValue(100)
                    blank.height_mm.setValue(140)
                    blank.position.setCurrentIndex(3)
                    controls = blank.findChild(QDialogButtonBox)
                    QTest.mouseClick(controls.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                except Exception:
                    failures.append(traceback.format_exc())
                    if blank is not None:
                        blank.reject()

            QTimer.singleShot(150, confirm_blank)
            button(dialog, "Blank pages")
            assert not failures, failures
            assert dialog.pages.page_plan()[-1].source_kind == "blank"
            final.extend(dialog.pages.page_plan())
            app.processEvents()
            QTest.qWait(400)
            dialog.grab().save(str(output / "organizer.png"))
            split = SplitPlanDialog(final, dialog)
            split.mode.setCurrentIndex(1)
            split.interval.setValue(3)
            jobs = [(output / "extract.pdf", final)] + [(output / name, group) for name, group in split.groups]
            split.close()
            with PlanReader(window.engine.document) as reader:
                expected.extend(reader.render(entry, 600).samples for entry in final)
            current_bytes = window.engine.document.tobytes()
            result = run_job(dialog, "Export QA", lambda **kw: export_plan(current_bytes, jobs, **kw))
            assert not result.error, result.error
            exported.extend(result.completed)
            button(dialog, "Apply Page Plan")
        except Exception:
            failures.append(traceback.format_exc())
            dialog.reject()

    QTimer.singleShot(200, interact)
    window._organize_pages()
    try:
        if failures:
            raise AssertionError(failures[0])
        assert window.engine.page_count == len(final)
        for document in (window.engine.document, fitz.open(output / "extract.pdf")):
            try:
                for page, pixels in zip(document, expected, strict=True):
                    scale = 600 / max(page.rect.width, page.rect.height)
                    assert page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).samples == pixels
            finally:
                if document is not window.engine.document:
                    document.close()
        assert window._undo_stack.undo_descriptions() == ["Advanced Page Organizer"]
        with fitz.open(output / "extract.pdf") as extracted:
            assert [p.get_text() for p in extracted] == [p.get_text() for p in window.engine.document]
            assert [p.rotation for p in extracted] == [p.rotation for p in window.engine.document]
        assert window._undo()
        assert window.engine.page_count == 4
        assert window._redo()
        assert window.engine.page_count == len(final)
        for document in (window.engine.document, fitz.open(output / "extract.pdf")):
            try:
                for page, pixels in zip(document, expected, strict=True):
                    scale = 600 / max(page.rect.width, page.rect.height)
                    assert page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).samples == pixels
            finally:
                if document is not window.engine.document:
                    document.close()
        assert window._undo()
        app.processEvents()
        window.grab().save(str(output / "viewer.png"))
        return {"passed": True, "frozen": bool(getattr(sys, "frozen", False)),
                "platform": app.platformName(), "final_pages": len(final),
                "exports": [str(p) for p in exported],
                "checks": ["native selection keyboard", "reverse", "duplicate", "rotate", "local undo/redo",
                           "crop drag/mm", "snapshot job", "interleave reverse B and padding", "blank",
                           "export job", "apply", "single main undo/redo"]}
    finally:
        window._confirm_discard_changes = lambda: True
        window.close()
        app.processEvents()


if __name__ == "__main__":
    destination = Path(sys.argv[1]).resolve()
    try:
        report = run(destination)
    except Exception:
        report = {"passed": False, "error": traceback.format_exc()}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)
