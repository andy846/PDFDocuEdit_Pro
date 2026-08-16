"""Compatibility launcher for the PyQt6 application.

The pre-migration Qt 5 monolith is preserved as
``backup/PDFdocuEdit_Pro_pre_pyqt6_20260812.txt`` for reference only.
"""

from main import main

if __name__ == "__main__":
    raise SystemExit(main())
