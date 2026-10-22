"""A failed/paused page must not strand this or the next document."""
import fitz
import pytest

from core.reader_lifetime import pause_readers
from tests.test_document_windows import editor as editor
from tests.test_open_performance import wait_until
from ui import pdf_canvas as canvas_module
from ui.pdf_canvas import PdfCanvas


def test_render_resumes_after_nested_reader_pause(qt_application):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Visible after resume")
    canvas = PdfCanvas()
    canvas.resize(800, 700)
    canvas.show()
    try:
        with pause_readers([canvas]):
            with pause_readers([canvas]):
                canvas.load_doc(doc)
                qt_application.processEvents()
            assert canvas._reader_pause_count == 1
            assert not canvas._pending
        wait_until(lambda: canvas._page_views[0].overlay._pixmap is not None)
        assert canvas._reader_pause_count == 0
    finally:
        canvas.clear()
        canvas.close()
        doc.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_render_failure_has_bounded_retry_and_next_pdf_still_opens(editor, tmp_path, monkeypatch, persistent):
    paths = []
    for i in range(2):
        path = tmp_path / f"source-{i}.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), f"Source {i}")
            doc.save(path)
        paths.append(path)
    render = canvas_module.render_page_image
    attempts = []
    def failing(doc, page, *args):
        if "Source 0" in doc[0].get_text():
            attempts.append(page)
            if persistent or len(attempts) == 1:
                raise ValueError("PRIVATE_RENDER_CONTENT")
        return render(doc, page, *args)
    monkeypatch.setattr(canvas_module, "render_page_image", failing)
    editor.queue_open_files([str(paths[0])])
    wait_until(lambda: not editor._open_queue_scheduled and not editor._tasks)
    first = editor._session
    if persistent:
        wait_until(lambda: 0 in first.canvas._render_errors)
        view = first.canvas._page_views[0]
        assert view.render_error.isVisible() and view.retry_render.isEnabled()
        for _ in range(3):
            first.canvas._fill_render_queue()
        assert len(attempts) == 2
        monkeypatch.setattr(canvas_module, "render_page_image", render)
        view.retry_render.click()
    wait_until(lambda: first.canvas._page_views[0].overlay._pixmap is not None)
    editor.queue_open_files([str(paths[1])])
    wait_until(lambda: not editor._open_queue_scheduled and not editor._tasks)
    second = editor._session
    wait_until(lambda: second.canvas._page_views[0].overlay._pixmap is not None)
    assert second is not first
    assert not second.canvas._pending and not second.canvas._reader_pause_count


def test_failed_queued_bootstrap_retains_previous_engine_and_history(editor, tmp_path, monkeypatch):
    from core.pdf_engine import PdfEngine
    from tests.test_document_windows import documents
    session = documents(editor, tmp_path, count=1)[0]
    with editor._mutation_transaction("Rotate") as allowed:
        assert allowed
        session.engine.rotate_pages([0], 90)
    previous = session.engine
    history = session.undo_stack.undo_count
    path = tmp_path / "replacement.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(path)
    replacement = PdfEngine()
    replacement.open(path)
    complete = editor._complete_pdf_open
    def fail_once(*args, **kwargs):
        monkeypatch.setattr(editor, "_complete_pdf_open", complete)
        raise ValueError("PRIVATE_BOOTSTRAP_CONTENT")
    monkeypatch.setattr(editor, "_complete_pdf_open", fail_once)
    with pytest.raises(ValueError):
        editor._queued_pdf_prepared(session, path, ("ok", replacement))
    assert session.engine is previous and previous.is_loaded()
    assert previous.is_modified and previous.document[0].rotation == 90
    assert session.undo_stack.undo_count == history
    wait_until(lambda: session.canvas._page_views[0].overlay._pixmap is not None)
    wait_until(lambda: not replacement.is_loaded())


def test_failed_bootstrap_keeps_form_draft_preview(editor, tmp_path, monkeypatch):
    from core.pdf_engine import PdfEngine
    from tests.test_inline_forms import make_form
    path = make_form(tmp_path / "draft-form.pdf")
    session = editor._open_in_new_tab_sync(str(path))
    editor._fill_form()
    editor._form_stage(session, session.form_draft.fields[0], "UNAPPLIED")
    draft = session.form_draft
    replacement = PdfEngine()
    replacement.open(path)
    complete = editor._complete_pdf_open
    def fail_once(*args, **kwargs):
        monkeypatch.setattr(editor, "_complete_pdf_open", complete)
        complete(*args, **kwargs)
        raise ValueError("Controlled bootstrap failure")
    monkeypatch.setattr(editor, "_complete_pdf_open", fail_once)
    with pytest.raises(ValueError):
        editor._queued_pdf_prepared(session, path, ("ok", replacement))
    assert session.form_draft is draft and draft.staged == {"First": "UNAPPLIED"}
    assert session.form_mode_active
    assert session.canvas._doc is draft.preview
    assert "UNAPPLIED" in session.canvas._doc[0].get_text()
    editor._discard_form_draft()


def test_failed_comparison_close_targets_displayed_document(editor, tmp_path):
    from tests.test_document_windows import documents
    first, second = documents(editor, tmp_path, count=2)
    editor.workspace.set_current_session(first)
    editor._toggle_split_view()
    first.set_split_source(second)
    first.split_canvas.documentCloseRequested.emit()
    wait_until(lambda: second not in editor._sessions)
    assert first in editor._sessions and first.engine.is_loaded()
