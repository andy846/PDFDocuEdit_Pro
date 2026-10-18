"""Measured synthetic scale checks through the real isolated worker and Qt UI."""

import time

import fitz
import pytest
from PyQt6.QtCore import QTimer

from composition.designer.mailpiece_dialog import MailpieceDialog
from composition.designer.overlay_workspace import OverlayWindow
from composition.overlay.model import EnvelopeSpec
from composition.pdf_source.model import EnvelopeSettings
from composition.pdf_source.source import inspect_source
from composition.production.resources import peak_memory
from tests.composition.test_multi_rule_detection import profile
from tests.composition.test_pdf_overlay_ui import finish
from tests.composition.test_workspace import wait_until


@pytest.mark.parametrize("pages", [2000, 8000])
def test_multi_rule_scan_ui_heartbeat_and_repeated_index(
    pages, qt_application, tmp_path, monkeypatch, request
):
    path = tmp_path / "synthetic.pdf"
    names = [f"TYPE_{i:02}" for i in range(4)]
    expected = []
    with fitz.open() as pdf:
        cursor = 1
        envelope = 0
        while cursor <= pages:
            count = min(1 + envelope % 4, pages - cursor + 1)
            expected.append([cursor, cursor + count - 1])
            for number in range(count):
                pdf.new_page().insert_text((40, 60), names[envelope % 4] if number == 0 else "Continuation")
            cursor += count
            envelope += 1
        pdf.save(path)
    settings = EnvelopeSettings(pages_per_envelope=1)
    source = inspect_source(path, settings, uniform=True)
    monkeypatch.setattr(OverlayWindow, "load_fonts", lambda self: None)
    monkeypatch.setattr(OverlayWindow, "render_preview", lambda self: None)
    window = OverlayWindow()
    window.apply_spec(EnvelopeSpec(source, settings).to_dict())
    window.show()
    dialog = MailpieceDialog(window)
    dialog.show()
    dialog.set_collection_profile(profile(*names))
    times = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: times.append(time.perf_counter()))
    timer.start()
    try:
        started = time.perf_counter()
        dialog.scan()
        wait_until(lambda: dialog.report is not None and not dialog.scan_worker, timeout=90)
        first = time.perf_counter() - started
        assert dialog.report["groups"] == expected and dialog.model.rowCount() == len(expected)
        assert not dialog.report["accepted"]
        assert len(times) > 5
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        longest = max(gaps, default=0)
        assert longest < 3, "Qt heartbeat stalled during the background scan"
        cache_stamp = dialog.cache_path.stat().st_mtime_ns
        started = time.perf_counter()
        dialog.scan()
        wait_until(lambda: dialog.report is not None and not dialog.scan_worker, timeout=90)
        repeated = time.perf_counter() - started
        assert dialog.cache_path.stat().st_mtime_ns == cache_stamp
        assert dialog.report["groups"] == expected
        request.node.user_properties.extend(
            [
                ("initial_seconds", round(first, 4)),
                ("cached_seconds", round(repeated, 4)),
                ("max_heartbeat_gap_seconds", round(longest, 4)),
                ("peak_parent_memory_bytes", peak_memory()),
            ]
        )
    finally:
        timer.stop()
        dialog.reject()
        finish(window)
