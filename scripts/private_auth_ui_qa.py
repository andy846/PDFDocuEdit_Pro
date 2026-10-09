"""Render isolated private UI fixtures; no account requests or desktop automation."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if getattr(sys, "frozen", False):
        raise RuntimeError("Source-only UI fixtures are not a production entry point.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=("dark", "light"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from PyQt6.QtCore import QEventLoop, QRect, QSettings, QTimer
    from PyQt6.QtGui import QFont, QFontDatabase
    from PyQt6.QtWidgets import QApplication

    from auth.application import PrivateApplication
    from auth.config import AuthConfig
    from auth.controller import AuthController
    from auth.model import Approval, timestamp
    from auth.store import ApprovalStore
    from auth.ui import AccountDialog, RecoveryDialog
    from core.viewer import PDFViewer
    from styles.components import global_style
    from styles.theme import apply_theme

    with tempfile.TemporaryDirectory(prefix="private-auth-ui-qa-") as settings:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings)
        app = QApplication([])
        # Qt's Windows offscreen plugin does not discover installed fonts.
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        app.setFont(QFont("Segoe UI", 10))
        app.setOrganizationName("PDFDocuEdit QA")
        app.setApplicationName("Private UI Fixtures")
        import ui.responsive
        ui.responsive.available_area = lambda widget: QRect(0, 0, 960, 640)
        apply_theme(app, args.theme)
        app.setStyleSheet(global_style())

        class Memory:
            value = None
            def get_password(self, *args):
                return self.value
            def set_password(self, *args):
                self.value = args[-1]

        config = AuthConfig("uifixture", "https://uifixture.supabase.co", "sb_publishable_fixture")
        controller = AuthController(SimpleNamespace(), ApprovalStore(config.project_ref, backend=Memory()))
        session = PrivateApplication(app, config, PDFViewer, controller=controller)
        session.login.show()
        app.processEvents()
        session.login.grab().save(str(args.output / "login.png"))
        now = timestamp()
        # In-memory fixture only. Nothing is written to Windows Credential Manager.
        controller.approval = Approval(config.project_ref, "f63613d9-81b8-4a36-b765-a37b6e9e0916",
                                       "fixture@example.invalid", "fixture", now, now)
        session.admit(controller.approval)
        viewer = session.viewer
        viewer._apply_theme(args.theme)
        viewer.resize(960, 640)
        app.processEvents()
        metrics = {"theme": args.theme, "scale": viewer.devicePixelRatioF(), "fixture_viewport": [960, 640],
                   "screen": [app.primaryScreen().size().width(), app.primaryScreen().size().height()],
                   "native_screen_test": False}
        for mode in ("pdf", "designer"):
            viewer._mode_controller.request_mode(mode)
            loop = QEventLoop()
            QTimer.singleShot(350, loop.quit)
            loop.exec()
            viewer.grab().save(str(args.output / (mode + ".png")))
            button = session.account_button
            assert button.isVisible()
            assert 0 <= button.mapTo(viewer, button.rect().topLeft()).x()
            assert button.mapTo(viewer, button.rect().bottomRight()).x() < viewer.width()
        dialog = AccountDialog(controller, lambda: None, viewer)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(args.output / "account.png"))
        dialog.reject()
        recovery = RecoveryDialog("The server confirmed this account is no longer approved.")
        recovery.show()
        app.processEvents()
        recovery.grab().save(str(args.output / "recovery.png"))
        recovery.hide()
        controller.stop()
        # Empty fixture window; no save prompt or user document is involved.
        viewer.removeEventFilter(session)
        app.removeEventFilter(session)
        viewer.close()
        app.processEvents()
        (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
