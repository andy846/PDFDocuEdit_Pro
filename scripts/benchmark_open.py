"""Repeatable opening benchmark without a committed large PDF fixture.

Run: python scripts/benchmark_open.py --pages 18000
Produces a valid minimal PDF with a flat page tree, then records preparation,
first-page and interactive timings. This is an architectural benchmark, not a
substitute for measuring image-heavy production PDFs or disconnected shares.
"""
import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def synthetic_pdf(path, count):
    # Write objects directly: repeated new_page() itself has quadratic fixture cost.
    offsets = [0]
    with Path(path).open("wb") as stream:
        stream.write(b"%PDF-1.4\n")
        def obj(number, body):
            offsets.append(stream.tell())
            stream.write(f"{number} 0 obj\n{body}\nendobj\n".encode())
        obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{index + 3} 0 R" for index in range(count))
        obj(2, f"<< /Type /Pages /Count {count} /Kids [{kids}] >>")
        for index in range(count):
            obj(index + 3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>")
        xref = stream.tell()
        stream.write(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            stream.write(f"{offset:010d} 00000 n \n".encode())
        stream.write(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return Path(path)


def main():
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    import core.viewer as module
    from core.settings import SettingsManager
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=18000)
    parser.add_argument("--layout", choices=("single", "continuous", "facing"), default="single")
    parser.add_argument("--thumbnails", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with tempfile.TemporaryDirectory(prefix="pdfdocuedit-benchmark-") as directory:
        directory = Path(directory)
        source = synthetic_pdf(directory / "synthetic.pdf", args.pages)
        module.SettingsManager = lambda: SettingsManager(directory / "settings.json")
        app = QApplication.instance() or QApplication([])
        start = perf_counter()
        window = module.PDFViewer()
        print(json.dumps({"pages": args.pages, "window_construction_ms": (perf_counter() - start) * 1000}), flush=True)
        original_create = window._create_session
        def create_session():
            session = original_create()
            session.canvas.set_layout_mode(args.layout)
            if args.thumbnails:
                session.nav_panel.show_panel("thumbnails")
            return session
        window._create_session = create_session
        window.show()
        window.queue_open_files([str(source)])
        timer = QTimer()
        def complete():
            session = window._session
            trace = getattr(session, "_open_trace", None)
            if trace and "time_to_first_page" in trace.values and "time_to_interactive" in trace.values:
                print(json.dumps(trace.values, sort_keys=True), flush=True)
                timer.stop()
                window.close()
                app.quit()
        timer.timeout.connect(complete)
        timer.start(20)
        QTimer.singleShot(60000, app.quit)
        app.exec()

if __name__ == "__main__":
    main()
