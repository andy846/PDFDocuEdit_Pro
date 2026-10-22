"""Narrow main-window integration for PDF Production Tools."""
from pathlib import Path

from PyQt6 import sip
from PyQt6.QtWidgets import QFileDialog

from core.pdf_backend import fitz


def open_production_workspace(window, workspace_type, section):
    mode = getattr(window, "_mode_controller", None)
    if mode:
        mode.request_mode("pdf")
    active = window.workspace.current_tool()
    if isinstance(active, workspace_type):
        active.select_section(section)
        return active
    session = window.workspace.current_session()
    if session is not None and session.form_draft is not None and session.form_draft.changed:
        window.info_bar.show_message("Apply or discard pending form edits before creating a production copy.", "warning", 0)
        return None
    pages = getattr(window, "_pdf_production_pages", None)
    if pages is None:
        pages = window._pdf_production_pages = {}
    key = id(session) if session is not None else None
    page = pages.get(key)
    if page is not None and not sip.isdeleted(page) and not page.stopped:
        window.workspace._tabs.setCurrentWidget(page)
        page.select_section(section)
        return page
    if session is None:
        paths, _ = QFileDialog.getOpenFileNames(window, "PDF production sources", "", "PDF (*.pdf)")
        if not paths:
            return None
    try:
        page = workspace_type(window)
        if session is not None:
            def capture():
                if session not in window._sessions or not session.engine.is_loaded():
                    raise ValueError("The source PDF was closed. Choose PDFs or reopen the source.")
                if session.form_draft is not None and session.form_draft.changed:
                    raise ValueError("Apply or discard pending form edits before refreshing the source.")
                previous = window._session
                try:
                    window._session = session
                    directory, snapshot = window._working_snapshot(session.engine.original_path or Path("document.pdf"))
                finally:
                    window._session = previous
                identity = (session.engine.document_id, session.engine.revision)
                security = session.engine.copy_security_context()
                permissions = security.get("output_permissions")
                def current():
                    return (session in window._sessions and session.engine.is_loaded()
                            and identity == (session.engine.document_id, session.engine.revision)
                            and not (session.form_draft is not None and session.form_draft.changed))
                return dict(paths=[snapshot], directory=directory,
                            label=Path(session.engine.original_path or "document.pdf").name,
                            page_count=session.engine.page_count, current_page=session.page,
                            security=security, editor=True, current=current,
                            scan_only=session.engine.is_encrypted() or (permissions is not None and not permissions & fitz.PDF_PERM_MODIFY))
            page.controller.refresh_factory = capture
            page.set_sources(**capture())
            page.pageRequested.connect(lambda number: window._font_preflight_page(session, number)
                                       if page.controller.editor_source and page.controller.is_current() else None)
        else:
            page.set_sources(paths=paths)
        pages[key] = page
        def remove():
            if pages.get(key) is page:
                pages.pop(key, None)
        page.closed.connect(remove)
        def open_output(path):
            if mode:
                mode.request_mode("pdf")
            window.load_file(path)
        page.outputReady.connect(open_output)
        page.activityChanged.connect(lambda _busy: window._merge_controller.sync_activity())
        window.workspace.add_tool_tab("pdf_production", page, "PDF Production Tools")
        page.select_section(section)
        return page
    except Exception as exc:
        if page is not None:
            page.controller.cleanup()
            page.deleteLater()
        window.info_bar.show_message(f"Cannot open PDF Production Tools: {exc}", "error", 0)
        return None
