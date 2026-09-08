# Background printing follow-up

Completed: 2026-09-07. Builds on the validated V2.5.4 stability checkpoint. Version metadata remains 2.5.4; this is the first V2.6 preparation step, not a published V2.6 release.

## 1. Modified files

- New `core/printing.py`: immutable job/settings records, PDF snapshot preparation, owned QImage rasterization and placement.
- New `ui/print_controller.py`: GUI-owned printer/painter state machine, one FunctionTask in flight, progress/results and cancellation.
- `core/viewer.py`: asynchronous single/batch entry points, application control suspension, task-bar integration and shared compatibility renderer.
- `dialogs/batch_print_dialog.py`: cancellation signal and safe hide/cancel on close.
- New `tests/test_printing.py`; updated `tests/test_tools_port.py`, `tests/test_ui_smoke.py` and `.github/workflows/ci.yml`.
- README and project review report updated; prior stability report preserved in `docs/archive/PROJECT_REVIEW_REPORT_2.5.4_checkpoint.md`.

## 2. Bugs/limitations addressed

| Before | After | Test coverage |
| --- | --- | --- |
| Synchronous rasterization blocked GUI progress and Cancel. | Worker preparation and rendering leave the event loop available. Cancellation uses threading.Event through FunctionTask. | A blocked render worker runs while a GUI timer continues ticking; cancel prevents the first spool job. |
| Long batch work needed nested event processing to receive input. | A queued controller advances one page at a time without processEvents or forced thread termination. | Real asynchronous single/batch PDF jobs, page counts and cancellation between pages. |
| Printer/worker ownership could become unsafe during a naive threading migration. | QPrinter, QPainter and native dialogs remain GUI-owned; only PDF preparation and owned QImages cross the worker boundary. | Thread identity assertions; cancelled dialog and printer newPage failure tests. |
| Closing a live batch dialog could destroy progress targets or falsely imply all work was already in the queue. | Close/Cancel sets cancellation and hides the dialog until worker cleanup completes. | Real dialog button/close integration test checks object lifetime and UI restoration. |
| System confirmation options could be lost on subsequent batch files. | Confirmed device/copy/colour/duplex/resolution settings carry across the batch; explicitly changed page layout also carries. | Both output jobs retain the confirmed copy count. |

## 3. Architecture

`PrintJob` and `PrintRenderSettings` are frozen dataclasses. A single-document job captures unsaved edits before dispatch. Each external batch file is prepared into an independent snapshot when its job starts. Only the current file snapshot and one rendered page image are needed; no list of all rasterized pages is accumulated.

Each FunctionTask finishes before the next is submitted. Worker results arrive at QObject slots on the GUI thread. The first QPainter/spool job is delayed until a first rendered page is available. Cancellation before that point produces no output job. Worker failures mark the file and advance to the next; printer errors end the painter before continuing. UI controls and task-bar state are restored after the controller finishes.

PyMuPDF preparation and rendering retain DOCUMENT_LOCK protection. The GUI does not retain that lock while waiting for worker results. Existing synchronous `_paint_documents()` and `_draw_print_page()` callers remain supported and reuse the same rendering/placement logic.

## 4. New/updated tests

Eight additional collected cases cover snapshot order/duplicates/unsaved edits, responsive GUI cancellation, preparation cancellation, failure continuation, system-dialog cancellation, printer page failure, cancellation before start, and actual viewer/dialog restoration. Existing single and batch tests now assert real asynchronous PDF output rather than patching out the old paint method. Existing mixed-orientation/scaling tests remain in the full suite.

## 5. Test results

Windows, Python 3.12.14; pinned PyQt6 6.8.1 / Qt 6.8.2 and PyMuPDF 1.26.6:

- Final full pytest: **330 passed in 157.72 seconds**, 31 modules, zero failures/errors.
- Focused UI/print-controller group: 15 passed.
- Source verification: passed.
- The final full-run log contains no native exception diagnostics. An earlier isolated print test emitted handled Windows native diagnostics (`0x80040155`) at QPrinter construction while its assertions still passed; these were retained in the local test log. The product-initialization integration group and final full run did not emit them. No exception handler or diagnostic suppression was added to conceal them.

New controller tests are included in the existing Linux/macOS core CI selection. Remote CI and real macOS/physical printer runs were not performed in this session.

## 6. Ruff result

`python -m ruff check .`: All checks passed. No new processEvents, shell=True, tempfile.mktemp or QThread.terminate path was introduced.

## 7. Remaining limits / next steps

- Cancel is cooperative: an in-flight PyMuPDF rasterization or native driver call must reach a checkpoint. Pages already accepted by a physical printer may not be retractable; native abort is requested for an active cancelled job.
- Capturing unsaved edits initially serializes the live document on the GUI thread under DOCUMENT_LOCK. Very large PDFs can pause briefly at this point. A batch file is snapshotted when its own preparation begins, not all files at batch submission time.
- Native printer creation, settings dialogs, painting and spool finalization remain GUI operations and may block inside platform drivers. Real printer/macOS validation is still needed.
- General mutation/undo transactions, further viewer decomposition and shared atomic IO remain separate V2.6 work. No installer was built or published.

## 8. Behaviour/API changes

Production single/batch print methods now schedule work and return before it finishes. Progress, completion, skipped files and cancellation update asynchronously. Existing synchronous low-level paint helpers remain available. Main-window editing controls are suspended for the job; closing the main window remains blocked until printing finishes or is cancelled. Batch-dialog Close now requests cancellation and hides safely. UI layout, icons, shortcuts and theme design were not redesigned.
