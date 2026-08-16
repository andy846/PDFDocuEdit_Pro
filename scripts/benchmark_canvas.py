"""Canvas performance benchmark: continuous scrolling and zoom coalescing.

Run with:

    .venv-pyqt6/bin/python scripts/benchmark_canvas.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PyQt6.QtWidgets import QApplication

from ui.pdf_canvas import LayoutMode, PdfCanvas

PAGES = 300


def build_document(path: Path, pages: int = PAGES) -> Path:
    with fitz.open() as doc:
        for index in range(pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 96), f"Benchmark page {index + 1}")
        doc.save(path)
    return path


def wait_renders(app: QApplication, canvas: PdfCanvas, timeout: float = 30.0) -> None:
    deadline = time.perf_counter() + timeout
    while canvas._pending and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(["pdfdocuedit-benchmark"])
    tmp = Path(tempfile.mkdtemp(prefix="pdfdocuedit-benchmark-"))
    source = build_document(tmp / "bench.pdf")

    canvas = PdfCanvas()
    canvas.resize(1100, 800)
    canvas.show()
    app.processEvents()

    with fitz.open(source) as doc:
        canvas.load_doc(doc, 0.8)
        wait_renders(app, canvas)
        canvas.set_layout_mode(LayoutMode.CONTINUOUS)
        wait_renders(app, canvas)

        bar = canvas.verticalScrollBar()
        start = time.perf_counter()
        for _ in range(20):
            bar.setValue(min(bar.maximum(), bar.value() + 400))
        canvas._apply_scroll_sync()
        wait_renders(app, canvas)
        scroll_ms = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        for index in range(10):
            canvas._queue_zoom(canvas._zoom * (1.2 if index % 2 == 0 else 1 / 1.2))
        canvas._apply_queued_zoom()
        wait_renders(app, canvas)
        zoom_ms = (time.perf_counter() - start) * 1000

        print(f"pages={PAGES}  scroll(20×400px)+sync: {scroll_ms:.1f} ms")
        print(f"zoom(10 ticks coalesced): {zoom_ms:.1f} ms")
        canvas.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
