# Merge PDF performance

## Call chain and bottlenecks

Before: viewport/dialog drop -> MergePDFDialog.add_paths -> resolve/is_file for every input -> _refresh -> fitz.open/page_count for uncached PDFs -> two stat calls per row -> create five QTableWidgetItems per input. Remove/reorder rebuilt all rows and repeated stat calls. These operations ran on the GUI thread, including network I/O.

Merge execution already used PDFViewer._run_task / FunctionTask. The expensive path was source open -> insert_pdf -> save(garbage=4, deflate=True) -> full page-tree validation -> atomic replacement. Level 4 always ran object and stream deduplication, even when compression was not requested.

## Changes

Merge uses a QAbstractTableModel/QTableView with fixed metadata column widths and visible-cell data access. Drops perform lexical normalization and a set-based duplicate check, then immediately show pending rows. A shared serial background queue fills cached metadata and inline unavailable/error states. Remove/reorder work from cached values. Closing cancels queued work and discards stale results; no GUI thread waits for an active read. The existing Batch Print table is preserved.

Merge remains a background task and now defaults to garbage=1 with no forced stream recompression. Deep compression preserves the old save settings as an explicit option. Source copies remain whole-document insertions, preserving internal links across pages. Output validation and same-directory atomic replacement remain mandatory; cancellation after saving or validation prevents replacing the destination. Native open/insert/save calls remain cooperative cancellation boundaries: cancelling does not interrupt an active native call.

PERF merge_add_files reports time to return from drop handling. PERF merge_pdf reports cumulative source opening, insertion, assembly, save, validation and total elapsed time. Paths are excluded from these timing records.

## Local measurements

Windows, Python 3.12, PyMuPDF 1.26.6; 200 synthetic PDFs with 10 text/vector pages each (2,000 pages), local disk. These are architectural benchmarks, not guaranteed production-file timings.

| Operation | Before | After |
| --- | ---: | ---: |
| Add 200 files to list | 108.7 ms | 1.3 ms |
| Reorder one file | 12.4 ms | 0.18 ms |
| Merge and validate | 55.31 s | 0.69 s |

Optimized merge breakdown: assembly 465 ms, save 53 ms, validation 153 ms. A separate run in the normal background-task path recorded 24 GUI heartbeat samples in 0.70 s, with a maximum gap of 151 ms. The new list timing excludes background metadata completion; the previous list blocked until metadata completed. Compression benefit and resulting file size depend on source content; deep compression can still take significantly longer.

Regression coverage includes 18,000 unavailable UNC paths without GUI filesystem/PDF reads, actual viewport file drops, a blocked metadata worker with live GUI heartbeat, removed/closed result rejection, merge order/internal links/rotation/metadata in both save modes, and atomic output preservation on cancellation or corrupt input.
