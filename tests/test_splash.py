from pathlib import Path

import pytest
from PyQt6.QtGui import QColor, QPixmap

from ui.splash import StartupSplash, create_splash, splash_pixmap


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("version", ["3.0.2", "3.1.0-beta"])
def test_version_changes_only_label_region(qt_application, dpr, version):
    source = QPixmap(1000, 560)
    source.fill(QColor("#b52020"))
    base = source.scaledToWidth(min(source.width(), round(520 * dpr))).toImage()
    result = splash_pixmap(source, version, max_width=520, dpr=dpr)
    assert result.devicePixelRatio() == dpr
    image = result.toImage()
    assert image.size() == base.size()
    changed = []
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixel(x, y) != base.pixel(x, y):
                changed.append((x, y))
    assert changed
    assert all(
        image.width() * 0.36 - 2 <= x <= image.width() * 0.73 + 2
        and image.height() * 0.60 - 2 <= y <= image.height() * 0.675 + 2
        for x, y in changed
    )


def test_version_is_not_baked_into_render(qt_application):
    source = QPixmap(1000, 560)
    source.fill(QColor("#b52020"))
    assert splash_pixmap(source, "3.0.2").toImage() != splash_pixmap(source, "3.1.0-beta").toImage()


@pytest.mark.parametrize("exists", [False, True])
def test_missing_or_corrupt_artwork_uses_fallback(qt_application, tmp_path, exists):
    path = tmp_path / "Splash.png"
    if exists:
        path.write_bytes(b"not a PNG")
    splash = create_splash(path, "3.0.2")
    assert not splash.pixmap().isNull()
    splash.close()


def test_real_artwork_preserves_transparent_corner(qt_application):
    source = QPixmap(str(Path(__file__).resolve().parents[1] / "Splash.png"))
    result = splash_pixmap(source, "3.0.2", max_width=source.width())
    assert result.toImage().pixelColor(0, 0) == source.toImage().pixelColor(0, 0)


def test_private_splash_dismissal_keeps_event_loop_responsive(qt_application):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtTest import QTest

    splash = StartupSplash(QPixmap(100, 100), minimum_ms=100)
    splash.show()
    splash.finish_startup()
    events = []
    QTimer.singleShot(0, lambda: events.append("login ready"))
    qt_application.processEvents()
    assert events == ["login ready"]
    assert splash.isVisible()
    QTest.qWait(150)
    assert not splash.isVisible()
    splash.deleteLater()


def test_splash_quit_and_manual_close_stop_pending_dismissal(qt_application):
    splash = StartupSplash(QPixmap(100, 100))
    splash.show()
    splash.finish_startup()
    assert splash._dismiss.isActive()
    splash.close()
    assert not splash._dismiss.isActive()
    splash.show()
    splash.finish_startup()
    qt_application.aboutToQuit.emit()
    assert not splash.isVisible() and not splash._dismiss.isActive()
    splash.deleteLater()
