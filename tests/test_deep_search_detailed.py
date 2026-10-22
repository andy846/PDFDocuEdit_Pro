"""Occurrence-level search, paging, filtering, and report regressions."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import fitz
from PyQt6.QtWidgets import QApplication

from core.deep_search import (
    SearchBatch,
    SearchFile,
    SearchHit,
    SearchIssue,
    parse_keywords,
    search_folder_detailed,
)
from core.search_report import ReportMeta, export_csv, export_html
from core.search_results_store import SearchResultsStore
from ui.deep_search_dialog import DeepSearchDialog
from ui.search_hits_model import SearchHitsModel


def _pdf(path: Path, *texts: str) -> None:
    with fitz.open() as document:
        for value in texts:
            page = document.new_page()
            page.insert_text((72, 72), value)
        document.save(path)


def _meta(*, complete: bool = True, scope: str = "All results") -> ReportMeta:
    return ReportMeta("apple, pear", "C:/reports", "2026-09-29T12:00:00+08:00",
                      1.2, 2, 2, True, False, complete, scope)


def test_detailed_search_counts_every_occurrence_and_keyword(tmp_path: Path) -> None:
    _pdf(tmp_path / "a.pdf", "apple apple pear", "apple")
    batches: list[SearchBatch] = []
    progress: list[tuple[int, int, str]] = []
    run = search_folder_detailed(
        tmp_path, "apple, pear, APPLE", on_batch=batches.append,
        progress=lambda current, total, message: progress.append((current, total, message)),
        batch_size=2,
    )
    hits = [hit for batch in batches for hit in batch.hits]
    files = [batch.file for batch in batches if batch.file]
    assert parse_keywords("apple, APPLE, pear") == ("apple", "pear")
    assert [(hit.page, hit.keyword) for hit in hits] == [
        (1, "apple"), (1, "apple"), (1, "pear"), (2, "apple")
    ]
    assert run.matches == 4 and run.matching_files == 1
    assert files[0].matches == 4 and files[0].matching_pages == 2
    assert any("page 2/2" in message for _, _, message in progress)


def test_detailed_search_checks_barcodes_even_when_text_matches(tmp_path: Path,
                                                                monkeypatch) -> None:
    _pdf(tmp_path / "a.pdf", "apple")
    monkeypatch.setattr("core.deep_search._barcode_values", lambda _page: ("apple apple",))
    batches: list[SearchBatch] = []
    search_folder_detailed(tmp_path, "apple", search_barcodes=True, on_batch=batches.append)
    assert [hit.source for batch in batches for hit in batch.hits] == [
        "text", "barcode", "barcode"
    ]


def test_store_pages_full_results_and_removes_interrupted_file(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["deep-search-store-test"])
    store = SearchResultsStore()
    try:
        hits = tuple(SearchHit("a.pdf", "a.pdf", 1, "apple", "text", "apple", i)
                     for i in range(450))
        store.add(SearchBatch(hits=hits, file=SearchFile("a.pdf", "a.pdf", 1, 1, 450, False)))
        store.add(SearchBatch(hits=(SearchHit("partial.pdf", "partial.pdf", 1,
                                              "apple", "text", "apple", 0),)))
        model = SearchHitsModel(store)
        model.configure()
        assert model.total == 451 and model.rowCount() == 200
        model.fetchMore()
        assert model.rowCount() == 400
        model.fetchMore()
        assert model.rowCount() == 451
        store.remove_incomplete_files()
        model.configure()
        assert model.total == 450
        assert store.counts() == (450, 1, 1)
    finally:
        store.close()
        assert app is not None


def test_html_csv_reports_escape_content_and_respect_filters(tmp_path: Path) -> None:
    store = SearchResultsStore()
    try:
        store.add(SearchBatch(
            hits=(SearchHit("C:/a<1>.pdf", "a<1>.pdf", 1, "apple", "text",
                            "apple <script>alert(1)</script>", 0),
                  SearchHit("C:/b.pdf", "b.pdf", 2, "pear", "barcode", "=HYPERLINK()", 0)),
            file=SearchFile("C:/a<1>.pdf", "a<1>.pdf", 1, 1, 1, False),
        ))
        store.add(SearchBatch(file=SearchFile("C:/b.pdf", "b.pdf", 2, 1, 1, False)))
        store.add(SearchBatch(issue=SearchIssue("C:/bad.pdf", "bad.pdf", "Cannot open")))
        html_path = export_html(store, tmp_path / "report.html", _meta(complete=False, scope="Current filters"),
                                ("C:/a<1>.pdf",), "apple", "text")
        content = html_path.read_text(encoding="utf-8")
        assert "a&lt;1&gt;.pdf" in content
        assert "&lt;script&gt;" in content and "<script>alert" not in content
        assert "Incomplete" in content and "Current filters" in content
        assert "1</strong><span>Occurrences" in content
        assert "bad.pdf" in content
        csv_path = export_csv(store, tmp_path / "report.csv", _meta())
        with csv_path.open(encoding="utf-8-sig", newline="") as input_file:
            rows = list(csv.DictReader(input_file))
        assert [row["Record type"] for row in rows] == ["match", "match", "error"]
        assert rows[1]["Context"] == "'=HYPERLINK()"
        assert rows[0]["Page"] == "1" and rows[0]["Keyword"] == "apple"
    finally:
        store.close()


def test_dialog_filters_export_scope_and_opens_hit_page(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["deep-search-dialog-test"])
    dialog = DeepSearchDialog(str(tmp_path))
    try:
        dialog.query.setText("apple, pear")
        for name, word, page in (("a.pdf", "apple", 2), ("b.pdf", "pear", 4)):
            path = str(tmp_path / name)
            dialog._receive_batch(SearchBatch(
                hits=(SearchHit(path, name, page, word, "text", word, 0),),
                file=SearchFile(path, name, page, 1, 1, False),
            ))
        dialog._show_all_hits()
        assert dialog._hits_model.total == 2
        dialog.file_filter.setText("a.pdf")
        assert dialog._hits_model.total == 1
        dialog.export_scope.setCurrentIndex(1)
        assert dialog._export_selection()[0] == (str(tmp_path / "a.pdf"),)
        emitted: list[tuple[str, str, int]] = []
        dialog.hitOpenRequested.connect(lambda *args: emitted.append(args))
        index = dialog._hits_model.index(0, 0)
        dialog._open_hit(index)
        assert emitted[0][0] == str(tmp_path / "a.pdf")
        assert emitted[0][2] == 2
    finally:
        dialog.close()
        assert app is not None


def test_dialog_worker_export_keeps_search_snapshot(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["deep-search-export-test"])
    dialog = DeepSearchDialog(str(tmp_path))
    try:
        dialog._run_query = "apple"
        dialog._run_folder = str(tmp_path)
        dialog._run_completed = True
        dialog._searched_at = "2026-09-29T12:00:00+08:00"
        dialog.query.setText("apple")
        path = str(tmp_path / "a.pdf")
        dialog._receive_batch(SearchBatch(
            hits=(SearchHit(path, "a.pdf", 2, "apple", "text", "apple", 0),),
            file=SearchFile(path, "a.pdf", 2, 1, 1, False),
        ))
        dialog.query.setText("changed after search")
        target = tmp_path / "worker-report.html"
        monkeypatch.setattr("ui.deep_search_dialog.QFileDialog.getSaveFileName",
                            lambda *_args: (str(target), "HTML file (*.html)"))
        dialog._export()
        deadline = time.monotonic() + 5
        while dialog._export_task is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert dialog._export_task is None
        report = target.read_text(encoding="utf-8")
        assert "apple" in report and "changed after search" not in report
        assert "a.pdf" in report
    finally:
        dialog.close()


def test_cancel_removes_unfinished_file_hits(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication(["deep-search-cancel-test"])
    dialog = DeepSearchDialog(str(tmp_path))
    try:
        complete = str(tmp_path / "complete.pdf")
        partial = str(tmp_path / "partial.pdf")
        dialog._receive_batch(SearchBatch(
            hits=(SearchHit(complete, "complete.pdf", 1, "x", "text", "x", 0),),
            file=SearchFile(complete, "complete.pdf", 1, 1, 1, False),
        ))
        dialog._receive_batch(SearchBatch(
            hits=(SearchHit(partial, "partial.pdf", 1, "x", "text", "x", 0),)
        ))

        class Cancelled:
            @staticmethod
            def is_cancelled():
                return True

        dialog._task = Cancelled()
        dialog._search_started_at = time.monotonic()
        dialog._search_finished()
        assert dialog._store.hit_count() == 1
        assert dialog.export_button.isEnabled()
        assert "partial results" in dialog.status.text()
    finally:
        dialog.close()
        assert app is not None
