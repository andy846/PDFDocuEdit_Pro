# Startup and PDF opening performance

## Investigation before the refactor

The original GUI path was `PDFViewer.load_file()` / `open_in_new_tab()` →
`_load_path()` → `_open_pdf()` → `PdfEngine.open()` → `_complete_pdf_open()`.
Shell requests already used `_prepare_pdf_engine()` in a worker, but most other
open actions did not. The worker path still performed expensive GUI completion.

| Original operation | Scaling / blocking risk | Treatment |
| --- | --- | --- |
| `SettingsManager.recent_files()` | `Path.is_file()` for every recent, including disconnected UNC shares | Read cached strings only |
| Welcome `_RecentThumbTask` | Reopen each recent PDF, read page 0 and rasterize it | Removed; reuse a small preview of a normally opened document |
| Command-line parsing / forwarding | Resolve and stat incoming paths before the window appears | Lexical path normalization; validate in the opener |
| Cached custom-stamp menu | Stat/resolve remembered image paths during construction | Populate from cached settings |
| Source validation and isolated working copy | Network latency and O(file size) copying | Background preparation, separately timed |
| Encrypted working-copy conversion | Potential whole-file rewrite | Background preparation, separately timed; preserve encryption/save behavior |
| `fitz.open`, metadata and page count | Native parsing; page-tree complexity can affect cost | Instrument separately; background worker |
| Canvas `_compute_rows()` / `_total_size()` | Load every page's rectangle, sometimes multiple times per layout | Sparse estimated rows refined for the viewport |
| Canvas visibility lookup | Walk preceding rows on scroll | Binary search over sparse row offsets |
| Thumbnail `load_document()` | Allocate a `QListWidgetItem` for every page | Count-only `QAbstractListModel` and `QListView` |
| Thumbnail widgets / rasterization | Previously already viewport-bounded; synchronous reader waits remained | Preserve bounded viewport widgets, LRU cache and priority; retire readers safely |
| Canvas quick preview | Synchronous PDF rasterization before background rasterization | Removed; rasterize in workers only |
| Outline construction | Native TOC extraction and widgets proportional to outline entries | Load when Outline is requested |
| `_refresh_annotate_list()` | Scan all pages on open, tab switch and page navigation | Reuse visible-page records; full scan only on Manage/Refresh request |
| Search, blank detection, OCR, Preflight | Potential whole-document work | Keep user-triggered; no open-time indexing or analysis |
| Inspector controls / search controls | Fixed-size UI initialization, page-count/range updates | Initialize and measure without document-wide analysis |

The original thumbnail panel did **not** create a QWidget for every page: its
widgets were already viewport-bounded. The eager per-page list items and other
whole-document scans were separate costs.

## Current flow

1. Build the window and Welcome Page from local settings. Display filenames,
   shortened locations, stored last-opened times, and cached previews or icons.
2. After Welcome is visible, submit availability probes to two daemon workers,
   with a bounded queue. A stuck network redirector cannot block Qt or shutdown.
   Unverified paths retain an unknown state; failures do not show modal dialogs.
3. Queue ordinary Open, recent, drop, shell, comparison and public `load_file()`
   requests. Source validation, copying, conversion and opening happen in a worker.
4. Install a prepared engine only if its target session still exists. Cancelled
   results explicitly release their native documents and temporary files.
5. Initialize the count-only thumbnail model, fixed-size controls and visible
   canvas pages. Unknown continuous/facing geometry uses first-page estimates.
   Visiting pages refines geometry while retaining the viewport anchor.
6. Deliver the first visible page. Only then enable thumbnail rasterization for
   a visible sidebar. Visible thumbnails outrank limited surrounding prefetch.
7. Load outline, full annotation lists, search and analyses on request.

Documents above 1,000 pages are identified as large documents in the session and
performance logs. The safe lazy policies apply to small documents too; no tools
are disabled. Full annotation management remains available through Manage or
“Refresh all document annotations”.

Thumbnail rendering has two workers per panel, at most 12 pending jobs, six rows
of overscan and an 80-image LRU. Model construction has no per-page Python loop.
Canvas rendering also caps pending work and discards obsolete generations.
Close/replacement retains reader leases until jobs finish before releasing the
engine; it does not wait for thumbnail jobs on the GUI thread. Explicit mutation
and undo paths retain their stronger reader-draining contract.

Welcome never schedules PDF rendering. Its small PNG previews are encoded in
local settings from an already-rendered first page. The initial Welcome layout
therefore needs no recent-source file access, even for cached previews.

## Diagnostics and measurements

`pdfdocuedit` INFO logs contain `PERF startup:` and `PERF open_document:` JSON
records. Durations use milliseconds and contain a correlation ID, no paths or
passwords. Phases include source validation, working copy, native open, metadata,
page count, page model, navigation, thumbnail panel, Inspector, search controls,
actual first-page rasterization, delivery latency and UI completion.

`time_to_first_page` marks installation of the first current-page image in its Qt
view, not an OS compositor measurement. `time_to_interactive` marks the next Qt
event-loop turn after document UI setup. Open totals start when the request is
queued, so `queue_wait` includes dispatch and preceding queued work. Startup
measurements currently cover main-window construction through its first event
loop turn, not Python interpreter/import time.

Measured on this Windows workspace, using a generated **blank, flat-page-tree
18,000-page PDF**, PyQt6 6.8.1 and PyMuPDF 1.26.6:

| Measurement | Original committed implementation | Refactored implementation |
| --- | ---: | ---: |
| Window construction | 189 ms | 166 ms |
| Time to Interactive | 1,410 ms | 325 ms |
| Time to First Page | Not independently recorded | 325 ms |
| Thumbnail model initialization | 195 ms | 0.13 ms |
| Automatic whole-document annotation scan | 547 ms | Not performed |
| Native open | Included in 143 ms engine preparation | 137 ms |
| Isolated working copy | Included in engine preparation | 2.38 ms |

A separate revised 100-page run had 136 ms TTI and 0.14 ms thumbnail model setup.
An 18,000-page continuous-layout run with the thumbnail sidebar visible reached
the first page in 409 ms and TTI in 439 ms. These are individual diagnostic runs,
not statistically controlled benchmarks or an Acrobat comparison.

The original measurement used the untouched Git HEAD source in a temporary
checkout, with the same synthetic fixture. No large PDF fixture is committed.

Reproduce current measurements:

```powershell
.\.venv-312\Scripts\python.exe scripts/benchmark_open.py --pages 18000
.\.venv-312\Scripts\python.exe scripts/benchmark_open.py --pages 100
.\.venv-312\Scripts\python.exe scripts/benchmark_open.py --pages 18000 --layout continuous --thumbnails
```

## Remaining cost and practical limits

The isolated working copy is intentionally retained: incremental saves, atomic
replacement and undo depend on it. Copying is off the GUI thread but still
precedes first-page delivery, so a very large file or slow source share can still
increase TTFF. Encrypted inputs may require a complete decrypted working copy.
These costs are separately logged rather than hidden behind a splash/progress
workaround. Removing them safely needs a separate change to source ownership and
save semantics, not simply opening the user's original file for incremental save.

Native parsing, a complex visible page, and unusually large annotation/label
structures can still cost time. The synthetic fixture verifies bounded
application work; image-heavy production PDFs and network throughput must also
be measured with the production logs. No real 18,000-page customer PDF was
available for this investigation.

## Regression coverage

`tests/test_open_performance.py` covers unavailable UNC recents, no-PDF Welcome
construction, cached previews, 100 versus 18,000 page thumbnail workloads,
count-only models, bounded canvas page access, lazy analysis, stale results,
responsiveness during blocked preparation, native-resource disposal, reader
retirement and small-document annotation management. It also covers destruction
before startup timers fire. Existing editor tests use the private synchronous
fixture helpers; public asynchronous open paths have separate event-loop tests.

A faster close exposed an existing sidebar startup timer that could run after
its widget was destroyed. It is now a widget-owned, single-shot timer, so Qt
cancels it with the widget. The callback is a receiver-bound Qt slot, avoiding
an anonymous closure that retained a destructing sidebar. Native thumbnail
rendering and document authentication/metadata also share the document lock;
source validation and file copying remain outside that lock. No extra `processEvents()` calls, splash delays or
loading animations were added to the application.


## Final verification (2026-09-17)

The complete regression suite passed: **576 tests in 561.86 seconds**, with no
reported warnings or native crashes. `git diff --check` and Ruff undefined/unused
symbol checks (`--select F`) passed. Additional regressions cover receiver-bound
sidebar timer destruction and serialization of background native PDF readers.

A final repeat after the test suite finished measured the following (milliseconds):

| Fixture / layout | First page | Interactive | Thumbnail initialization |
| --- | ---: | ---: | ---: |
| 100 pages, single | 173 | 174 | 0.12 |
| 18,000 pages, single | 398 | 398 | 2.55 |
| 18,000 pages, continuous, sidebar visible | 471 | 507 | 0.20 |

These repeats show normal run-to-run variation from the earlier measurements.
The final 18,000-page single-layout run spent 158 ms in native open, 2.11 ms
copying, and 71.82 ms initializing the page model. The measured initial workload
remains viewport-bounded; tests check operation counts rather than enforcing a
machine-dependent timing threshold.


## Thumbnail scrollbar correction (2026-09-18)

Manual testing exposed an incorrect visible-range fallback: hit tests at x=2
landed in the QListView margin, while scrollbar-pixel division counted row
spacing incorrectly. The estimated range drifted increasingly far from the
actual viewport, eventually becoming empty at the end of an 18,000-page list.
This scheduled thumbnails for invisible pages and left visible rows unpopulated.

Visible bounds now use binary searches over Qt's actual `visualRect()` geometry,
with O(log page_count) probes and no per-page allocation. Existing bounded
rendering, caching, and current-viewport refill remain intact. Loading every
thumbnail is unnecessary and would not repair this geometry mismatch.

Regression coverage uses independent viewport-rectangle intersections, distant
forward/backward scrollbar jumps, hide/show, cache restoration, and real
18,000-page PDF rendering after a drag stops. The focused architecture, thumbnail
and reorder run passed 25 tests; static checks and `git diff --check` passed.


## Large-document Advanced Page Organizer (2026-09-18)

The old Organizer constructed a QWidget card for every page, read each page's
rotation, and loaded every page's size during layout. Dialog initialization then
restored the grid, repeating the construction. Thumbnail batches ran from a Qt
timer but performed native rasterization on the GUI thread. The first unchanged
preview also serialized the entire PDF into another document.

Documents above 1,000 pages now use `VirtualOrganizerGrid`:

- Construct only the dialog controls and a QListView/QAbstractListModel grid.
  A delegate paints cards; there are no per-page QWidget instances.
- After the window is shown, prepare lightweight page-plan records in one worker.
  Reading original rotations is still a page-count-proportional metadata pass,
  needed by the existing absolute-rotation page-plan contract. It runs in the
  background, reports actual progress, checks cancellation between pages, and
  does not generate thumbnails. Editing controls enable when the plan is ready.
- Render only visible pages plus one neighboring row, one job at a time, with a
  128-image LRU. Each completion chooses the latest viewport, so there is no
  backlog of obsolete queued pages after a scrollbar jump. Immutable plan-entry
  keys prevent an old rotation/crop preview from replacing a newer one.
- Rasterization and dimensions run in the worker. Unchanged-page previews use
  their original resource context directly, avoiding a whole-document copy.
  Changed-page previews retain the isolated-copy path to preserve crop/rotation,
  forms and optional-content correctness.
- Cancel keeps the dialog responsive while its current native reader reaches a
  safe checkpoint; only then may the dialog release sources or return to the
  caller. Background failures appear in the dialog or diagnostic log.
- Existing selection, reorder, rotate, duplicate, delete, insert/replace,
  blank-page, restore and plan undo/redo commands use lightweight records.
  Smaller documents retain their existing animated card grid.

`PERF organizer` records plan-interactive and first-preview timings. A styled
18,000-page blank synthetic PDF measured 121 ms to construct the dialog and
503 ms from construction start to plan readiness (internal grid trace: 477 ms).
The initial dialog had 65 descendant widgets, independent of the page count.
The last four page previews were verified at the end of the scrollbar.

Validation: **149 relevant tests passed in 18.96 seconds**, including six new
large-document regressions, existing Organizer crop/rotation/export tests,
engine/mutation tests and opening-architecture tests. The new tests cover blocked
reader responsiveness, cancellation, source-rotation preservation, immutable
preview identity, actual viewport intersections after resizing, and preparation
failure. Static symbol checks and `git diff --check` passed. A rendered screenshot
was inspected for layout and correct tail-page positions.

Scope: this changes opening and browsing the large Organizer. Explicit Apply
still uses the existing atomic, undoable document-mutation transaction; full
plan assembly, history snapshots and some explicit tool dialogs can remain
expensive. It does not claim constant-time application of an 18,000-page edit,
or measured performance on the customer's production PDF.
