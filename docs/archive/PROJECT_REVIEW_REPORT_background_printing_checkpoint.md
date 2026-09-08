# PDFDocuEdit Pro stability and background printing report

Stability checkpoint: 2026-09-06. Background printing follow-up: 2026-09-07. Base source: V2.5.3. Current version metadata remains V2.5.4.
Scope: completed stability stages A–E plus the requested next step, background printing. The general V2.6 transaction/undo framework remains deferred. See [background printing report](docs/BACKGROUND_PRINTING_REPORT.md) for the latest implementation and validation.

## 1. Modified files

| Area | Files |
| --- | --- |
| PDF integrity | `core/pdf_engine.py`, `tests/test_pdf_engine.py` |
| OCR | New `core/ocr_language.py`; `core/ocr.py`, `core/analysis.py`, `dialogs/ocr_dialog.py`, `tests/test_ocr.py` |
| Capabilities / validation | `core/capabilities.py`, `core/verapdf.py`, `tests/test_v2_analysis.py` |
| Build / CI | `scripts/build.py`, `scripts/verify_source.py`, `pyproject.toml`, `.github/workflows/ci.yml`; new `tests/test_stability_contracts.py` |
| Printing / public theme | `core/viewer.py`, new `core/printing.py` and `ui/print_controller.py`, `dialogs/batch_print_dialog.py`, `main.py`, `scripts/render_motion_qa.py`, `tests/test_ui_smoke.py`, `tests/test_tools_port.py`, new `tests/test_printing.py` |
| Associations | `core/file_association.py`, `installer/PDFDocuEditPro.iss`, `tests/test_file_association.py` |
| Settings | `core/settings.py`, `tests/test_settings.py` |
| Version / source contracts | `core/resources.py`, `installer/PDFDocuEditPro.version.txt`, `tests/test_source_contract.py`; version fields in the build/installer/project files above |
| Documentation / repository | `README.md`, this report, new `docs/RELEASE_NOTES_2.5.4.md`, `.gitignore`, `docs/archive/` |

Fifteen historical files were moved without content changes: `backup/` (12 files), `pytest_v21.txt`, `PDFdocuEdit_Pro.txt`, and `version_PM.png`. Each archived file's Git blob hash matches its original. The previous review report was also copied to `docs/archive/PROJECT_REVIEW_REPORT_pre_2.5.4.md`. Ruff excludes the historical archive, matching the previous exclusion of `backup/`. Existing local launch logs remain on disk and are now ignored.

`ANNOTATE_TOOLS_VERIFICATION_PLAN.md` was already valid UTF-8. Its Chinese text and byte round-trip were verified; it contains no U+FFFD replacement characters. No unnecessary transcoding was performed. Requirement pins and the Windows-only OCR packaging rule in the spec were already correct and remain intact.

## 2. Bugs fixed

| Issue | Before | After | Test coverage |
| --- | --- | --- | --- |
| Page-plan rollback | Closed the live document before reopening its backup; restore errors lacked a clear engine-state contract. | Opens the restored document first, retains save context, and raises a chained `PdfEngineError`. A failed restore explicitly invalidates the document and requires reopening. | `test_mutation_rollback_integrity`, plan variants: injected second insertion failure, successful/failed restore, text/rotation/page count, save context, saving and continued use. |
| Partial insertion | A later insertion failure could leave earlier pages inserted. | An operation backup restores the entire destination on insertion failure. | Same fault-injection test, insert variants, including failed restore and reopening. |
| Insertion order | Caller order was already retained but undocumented. | Explicit zero-based caller order and duplicate contract; no sorting introduced. | `test_insert_pages_preserves_caller_order_and_duplicates`: `[5, 2, 5]`. |
| OCR language | Analysis used `eng+chi_tra`, while the OCR service only accepted the other mixed spelling. | One normalizer and option list; canonical form `chi_tra+eng` across dialog, service, analysis and asset detection. | `test_shared_language_contract` covers both mixed aliases and single languages through real PDF rendering and mocked Tesseract commands; unsupported language test. |
| veraPDF discovery | Capability detection duplicated discovery and omitted `VeraPDF/`. | Capability detection calls `find_verapdf_runtime()`; both spellings work in bundle and frozen executable fallback locations. | `test_verapdf_discovery_is_shared`, both names and frozen/development cases; existing runtime/Java tests retained. |
| Python requirement | Build and source verifier accepted 3.11–3.13 despite project metadata allowing only 3.12. | Both accept only Python 3.12.x; build main rejects unsupported versions before work starts. | Build rejection/acceptance tests and source-verifier tests; CI remains Python 3.12. |
| macOS OCR contract | Spec already excluded OCR on macOS, but build output was not explicit. | README, build output and capability reason say: “OCR is not bundled in the macOS build.” | `test_macos_ocr_contract`; inspected existing Windows-only spec rule. |
| Print re-entrancy | Single and batch progress callbacks pumped GUI events. | Worker preparation/rendering with one image in flight; GUI-thread printer/painter lifecycle; Event cancellation and Qt progress; registered actions and editing widgets suspended/restored. All PyMuPDF worker access retains DOCUMENT_LOCK protection. | Real asynchronous single/batch PDF output, live GUI timer during blocked rendering, worker thread checks, cancellation before spool/during preparation/after a page, error continuation, native-dialog cancellation, printer page failure, UI/dialog lifetime and source contract. |
| Association lookup | UserChoice followed only by merged HKCR lookup. | UserChoice retains priority, then explicit HKCU, HKCR and HKLM classes fallback. | Existing precedence test and `test_default_lookup_reaches_machine_classes`. |
| Association removal | Runtime registration lacked a symmetric remover. | `unregister_default_app()` removes matching own values, leaves UserChoice and foreign values intact, and deletes shared keys only when empty. Installer OpenWith values also use empty-key cleanup. | Mock-registry register/unregister round trip, foreign defaults/values, UserChoice preservation, empty key removal and idempotence. No real registry writes during tests. |
| Settings null fallback | An explicit null bypassed a supplied default. | Null follows fallback handling; false, zero and empty strings remain values. | `test_get_defaults_for_null_and_missing_preserves_false_values`; existing settings tests. Caller audit found no dependence on distinguishing missing from null through `.get()`. |
| veraPDF success message | The current source already excluded raw stderr, but returned an empty success message. | Compliant results report “veraPDF validation completed successfully.” | Existing private-Java test updated with noisy stderr and an exact normalized message assertion. |
| Theme API | Main, QA script and a test called a private method. | Public `PDFViewer.apply_theme()` delegates to the retained private method; external callers migrated. | Existing main-window theme smoke test now exercises the public method. Visual design is unchanged. |

## 3. Architectural changes

Shared boundaries include the rollback restore helper, OCR language contract and veraPDF finder. The follow-up adds immutable print inputs/settings and a GUI-owned PrintController with one cancellable FunctionTask at a time. No general mutation transaction framework, automatic low-level undo snapshots, viewer decomposition or shared atomic-IO migration was introduced. Existing DOCUMENT_LOCK coverage is retained. Worker PDF preparation and rasterization hold the lock; no GUI-owned lock is held while waiting for a worker.

Production single/batch rendering is now asynchronous; the synchronous `_paint_documents()` compatibility helper is retained. The guard uses registered application actions plus editing widgets, without traversing Qt-internal actions. Printer/dialog operations remain on the GUI thread. Batch confirmation settings carry across files; source-driven page layout remains per file unless explicitly overridden.

## 4. New/updated tests

There are 34 additional collected cases relative to the 296-case base, giving 330 cases across 31 test modules. New modules `tests/test_stability_contracts.py` and `tests/test_printing.py` cover stability contracts and the background print lifecycle; both are included in the existing Linux/macOS core CI selection. The other tests are additions or strengthened assertions in the files listed above.

Regression tests cover fault recovery, failed rollback, order/duplicates, language normalization, bundle discovery, unsupported Python versions, macOS OCR messaging, print action/state restoration and cancellation, registry preservation, settings defaults and the public theme call.

## 5. Test results

Validated on Windows with project-pinned PyQt6 6.8.1 / Qt 6.8.2 and PyMuPDF 1.26.6. A dedicated project-local Python 3.12.14 environment was created to match the supported runtime contract.

| Checkpoint | Result |
| --- | --- |
| Stage A engine + undo | 39 passed |
| Stage A full suite, initial Python 3.11 environment | 301 passed |
| Stage B related tests | 52 passed |
| Stage B full suite, initial Python 3.11 environment | 315 passed |
| Stage C revised full suite, initial Python 3.11 environment | 317 passed |
| Stage D related tests, Python 3.12 | 58 passed |
| Updated print/task/build tests, Python 3.12 | 20 passed |
| Full functional suite, Python 3.12.14 | 322 passed in 144.57 seconds |
| Final metadata/source/build contracts after archiving | 18 passed |
| V2.5.4 stability checkpoint, Python 3.12.14 | 322 passed in 151.12 seconds; 30 modules |
| Background printing follow-up, Python 3.12.14 | **330 passed in 157.72 seconds; 31 modules; zero failures/errors** |
| Source verification | Passed |
| Archive integrity | All 15 moved files match original Git blobs |
| Annotation plan encoding | Valid UTF-8, intact Chinese text, no replacement characters |

Earlier print-guard iterations produced native Windows access violations in the full suite. A test monkeypatch lifetime issue was corrected, and the production guard was narrowed from recursive Qt action discovery to the existing application action registry. Those failed runs were not counted as passing validation. The stability checkpoint passed 322 cases. The latest background printing follow-up passed all 330 cases in 157.72 seconds, with zero failures/errors; its JUnit report confirms 31 modules. The final full-run log contains no native exception diagnostics.

The CI configuration has Windows full pytest, Ruff and Linux/macOS core tests. Actual remote CI jobs were not triggered from this session; local results do not claim execution on macOS or Linux.

## 6. Ruff result

`python -m ruff check .`: **All checks passed.**

`python scripts/verify_source.py`: **Source verification passed.**

`git diff --check`: passed. Active-source safety checks found no forbidden `shell=True`, `tempfile.mktemp`, `QThread.terminate` or legacy Qt APIs. The print source contract additionally rejects `QApplication.processEvents()` in the viewer.

## 7. Remaining known issues

| Item / reason | Risk or limitation | Next step |
| --- | --- | --- |
| Cancellation is cooperative; the initial live-document snapshot and native printer calls still run on the GUI thread. | Cancel cannot interrupt an active PyMuPDF/native call; already-spooled pages may not be retractable. Very large initial snapshots can briefly pause the UI. | Validate real printer drivers and large documents; evaluate snapshot cost in the future transaction architecture. |
| Real platform integrations were not executed here. | Physical printer drivers, macOS packaged runtime and actual external-binary workflows remain unverified by this repair. | Run target-platform smoke tests and optional binary integration CI before release packaging. |
| macOS OCR is not bundled by the existing product contract. | OCR remains unavailable on macOS. | Bundle and validate a supported native runtime if product scope expands. |
| V2.6 architecture is intentionally deferred. | Other mutations still rely on their current caller/undo discipline; this patch does not promise transaction semantics for every engine method. | Introduce one logical-action transaction/undo abstraction, then gradual viewer and atomic-IO extraction. |
| Rollback requires a PDF backup in memory. | Large documents can require substantial temporary memory; a restore failure requires reopening. | Evaluate a disk-backed backup policy in the future transaction layer. |
| No installer was built, signed or published. | Source version is V2.5.4; README download filenames still identify the existing V2.5.3 release. | Run the native release build and platform validation before publishing new artifacts. |

## 8. Any behaviour/API changes

- Mutation errors now raise chained `PdfEngineError` with an explicit restored/broken-state message. Successful operation behavior is retained.
- `insert_pages()` explicitly documents zero-based input, caller order and duplicates.
- `normalize_ocr_language()` accepts both mixed aliases; canonical output is `chi_tra+eng`.
- Python 3.11 and 3.13+ are rejected for builds/source verification; only 3.12.x is supported.
- `SettingsManager.get()` now uses fallback behavior for null values. No settings file format change.
- Added `unregister_default_app()` and public `PDFViewer.apply_theme()`; the existing private theme method remains available.
- Single and batch printing now return to the event loop while workers prepare/render pages. Commands and editing widgets remain unavailable until completion/cancellation. Closing the batch dialog cancels safely. Cancel respects the safe-checkpoint limitations above.
- veraPDF capability backend descriptions now come from the shared runtime finder. Successful compliant validation has a normalized user-facing message.

PDF save/encryption format, page ordering, undo granularity, shortcuts, icons, UI layout and theme visual design were not redesigned.
