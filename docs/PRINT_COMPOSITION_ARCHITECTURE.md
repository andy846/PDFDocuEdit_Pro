# Print Composition implementation note

Date: 2026-10-01 (Hong Kong). Isolated worktree starts at stable main/v2.5.15; the measurement-calibration feature branch is preserved. Local tag pre-v3.0-v2.5.15 provides rollback.

## Reuse and conflicts

Reuse PyQt6 6.8.1 theme tokens/icons, PyMuPDF 1.26.6 rendering and fonts, fontTools, Pillow, core.io_atomic.atomic_output and core.pdf_io.validate_pdf_file. Existing core.analysis inspection remains an optional postflight service. Existing FunctionTask is suitable for short non-PDF import tasks, but production and preview use a subprocess to avoid concurrent PyMuPDF access with the editor. No PdfEngine, DocumentSession, editor undo snapshots or live fitz documents cross the process boundary.

DocumentWorkspace tab bookkeeping is coupled to DocumentSession. Therefore Composition uses a separate QMainWindow owned by the application, launched from Welcome. Its undo stack stores declarative template states and has no editor PDF snapshots. main.py only dispatches the worker flag before normal application startup; core/viewer.py only launches the workspace.

## Output strategy

DocumentWriter's existing Story route does not directly accept background-page replay in the pinned API (DeviceWrapper mismatch in a feasibility probe). Use ordinary one-page composition into bounded 500-page documents, then qpdf content-preserving assembly. Font resources are shared within each chunk, never silently substituted. Reconciliation compares input/processed/successful/failed/page/file counts. Publish a new job directory by same-parent rename after all artifacts pass validation. A failed or cancelled job keeps a diagnostic JSON/CSV directory without a PDF.

## Assets and distribution

Pinned qpdf 12.4.2 msvc64 archive SHA-256 db87077e683630c1217e0e8f9a20a9749d952ab676e881c3689187763a5de25d; segno 1.6.6 (BSD), python-barcode 0.16.1 (MIT), Noto Sans and Noto Sans CJK HK (SIL OFL). Build preparation records per-file hashes and immutable source URLs. Binary/font files remain ignored build assets; the manifest and prepare script are tracked. The feature is disabled by default until a complete development build explicitly enables it.

## Tests and packaging impact

Add composition tests beneath tests/composition (discovered by existing pytest testpaths); add a headless subset to cross-platform CI. Add composition to setuptools package discovery and active source validation. PyInstaller includes worker imports, bundled qpdf DLLs and fonts only for enabled Composition builds. The stable release constants are intentionally retained until release gates are satisfied.
