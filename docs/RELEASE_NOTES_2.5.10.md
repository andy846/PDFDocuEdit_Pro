# PDFDocuEdit Pro v2.5.10

## Startup and large-document performance

- Show Welcome from cached settings; check recent-file availability after the window appears. Disconnected network recents no longer block window construction.
- Redesigned Welcome with Open PDF, drag-and-drop guidance, recent locations and last-opened information, cached previews, and existing quick tools.
- Prepare documents in background workers. Use lightweight page models, sparse continuous/facing geometry and bounded visible-first rendering.
- Load outlines and full annotation lists on demand. Search, OCR, blank detection and Preflight remain available when requested.
- Fix thumbnail scrollbar geometry drift on long documents, including empty previews after dragging to the end.
- For documents above 1,000 pages, Advanced Page Organizer opens a virtual grid, prepares the page plan in the background with progress/cancellation, and renders only visible/nearby previews.
- Preserve Organizer selection, reordering, rotation, duplicate/delete, insert/replace and plan undo/redo. Unchanged previews no longer serialize the complete source PDF.
- Add structured PERF logs and regressions using synthetic 18,000-page documents. Fix deferred Qt callback and reader-retirement lifecycle issues.

## Practical limits

Synthetic blank-document timings are architectural measurements, not an Acrobat comparison or a guarantee for production PDFs. Isolated working-copy creation still precedes the first document page; slow network sources and encrypted inputs can take longer. Organizer Apply retains the existing atomic, undoable mutation transaction and may still take time for large edits. Smaller Organizers retain their animated card grid.

## Windows packages

- Managed Portable ZIP: extract the complete package to a writable location and run Launcher.exe.
- Update ZIP, update.json and update.sig: signed artifacts for existing managed installations.
- Matching SHA-256 files are included. Do not extract a Managed Portable ZIP over an existing managed installation.

Repository visibility is unchanged. Private GitHub Releases require an authorized account; anonymous in-app update requests cannot access a private repository.

See [architecture and measurements](STARTUP_AND_OPEN_PERFORMANCE.md) for implementation details and diagnostic interpretation.


## Release validation

- 584 automated tests passed on Windows/Python 3.12; full Ruff, source verification and dependency checks passed.
- Frozen acceptance using the exact release module archive and runtime passed: asynchronous opening, rotation/edit, save/reopen content, Undo/Redo, 18,000-page Organizer, tail-page previews and bounded cache.
