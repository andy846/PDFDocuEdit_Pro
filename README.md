# PDFDocuEdit Pro

PDFDocuEdit Pro is a PyQt6 and PyMuPDF desktop workspace for viewing, editing,
converting and processing PDF documents on Windows and macOS.

## Development

Use Python 3.11–3.13 (3.12 recommended). Platform-specific Qt and native packages must be installed in
separate environments; do not reuse a Windows environment on macOS or mix Intel
and Apple Silicon packages.

```bash
python3.12 -m venv .venv-pyqt6
.venv-pyqt6/bin/python -m pip install -r requirements-dev.txt
.venv-pyqt6/bin/python scripts/verify_source.py
.venv-pyqt6/bin/python -m pytest
.venv-pyqt6/bin/python main.py
```

Optional features are enabled automatically when their runtime is present:
LibreOffice or Microsoft Office for Office conversion, Ghostscript for
PostScript, and zbar for barcode scanning.

## Detailed workflows

The PyQt6 interface retains the full option-page workflows from the original
application rather than reducing tools to one-click actions. This includes
rule-based page extraction/deletion/splitting, three-mode page insertion,
thumbnail organization, document analysis, single and batch print profiles,
batch Office/TXT/PostScript conversion, compression, overlay, region text
extraction, CSV/Excel merge rules, barcode batch scanning and PDF security
permissions. Dialog geometry is remembered per tool and long-running batch
operations report progress with cooperative cancellation.

## Release builds

Run `python scripts/build.py` in a clean Python 3.11–3.13 environment on each target:

- Windows 10/11 x64 produces an Inno Setup installer.
- Apple Silicon macOS produces an arm64 App and DMG.
- Intel macOS produces an x86_64 App and DMG.

macOS architecture packages are intentionally built separately. Signing and
notarization remain optional for internal builds. Release CI may set
`PDFDOCUEDIT_CODESIGN_IDENTITY` and `PDFDOCUEDIT_NOTARY_PROFILE`. Windows CI
may set `PDFDOCUEDIT_SIGNTOOL`, `PDFDOCUEDIT_CERT_SHA1`, and optionally
`PDFDOCUEDIT_TIMESTAMP_URL`. With no variables set, the pipeline produces the
unsigned/internal installer described by the release plan.
