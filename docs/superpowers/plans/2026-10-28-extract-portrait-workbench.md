# Portrait extraction workbench implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox syntax.

**Goal:** Implement the owner's approved portrait-A4 mockup and optional trial / one-action Excel workflow.

**Architecture:** Recompose existing Quick widgets in `ExtractionWorkbench`: full-height PDF left (~48%), settings/results/actions right. Use existing scan, rows and atomic export workers; chain complete extraction to the existing save chooser only after current full results are ready. No new extraction model or backend.

**Tech Stack:** Existing Python 3.12 / PyQt6 / SQLite / openpyxl / QSettings.

**Spec:** Owner-approved mockup `extract-portrait-workbench.html` in this chat's visualization directory and the GO WITH PLAN instruction. Its example data are illustrative, not production metrics. English product copy follows the existing app. Existing geometry, worker, export and Workflow safety contracts remain binding.

## Global constraints

- Work on D:\Python_Project\PDFdocuEdit_Pro local main, baseline 0d120faf31dd2ce1edce70317195a8e7259227b1.
- No branch/worktree, version bump, dependency, push or release. Preserve unread/untracked BOCHK.pdmp and the running user app.
- Reuse Region/ExtractionSpec, preview/raster lifecycle, SQLite pagination, exports and Workflow. No engine/schema/authorization changes.
- Keep notes/probes under build/probes/extract-portrait; no customer documents/settings in QA.

## Review focus

- Trial even when it covers every selected page must never authorize full-result export; primary action must scan fully.
- Cancel/failure/close/source changes between scan and chooser must prevent unintended export and retain existing files.
- Repeated primary clicks and rows-worker overlap must not start duplicate or silently dropped export jobs.
- Old layout preferences must not transpose split axes; geometry-only migration and new proportions must restore safely.
- Portrait and landscape / narrow / high-DPI / long-status states must preserve PDF height and reachable actions without resetting splits on resize.

## Task 1: Portrait layout

Files: modify `dialogs/extraction_workbench.py`, `dialogs/quick_text_extractor.py`; tests `tests/test_quick_extraction_workbench_ui.py`.
Interfaces: keep existing widget references; `wide` becomes horizontal PDF/right; `right_splitter` settings/results vertical; settings `editor_splitter` fields/properties horizontal. `finish_workbench()` attaches existing selection/status/progress/action widgets. Keep focus/collapse/restore APIs, new visual QSettings group with geometry-only v2 migration.

- [x] Add failing tests: at 1280×800 and 960×640 PDF view is taller than wide, table stays right with 8/6 full rows, controls reachable; resizing retains horizontal and right vertical proportions; focus/collapse restore and reopen retain valid proportions.
- [x] Implement left full-height preview and right settings/results/actions with compact common properties; move geometry/advanced rules into existing expansion. Preserve theme, keyboard, labels and lazy raster behavior.
- [x] Run workbench and existing Quick UI modules separately, plus synthetic light/dark 100/200% screenshots; inspect actual viewport, PDF and footer bounds.

## Task 2: One-action complete Excel export

Files: same Quick dialog, new `tests/test_quick_extraction_export_ui.py`, `scripts/ci_plan.py`; update operator/validation docs.
Interfaces: `extract_and_export()` reuses current valid full results or calls `start_scan(on_ready=...)`; `load_rows(..., on_ready=...)` invokes continuation only after successful current rows; `choose_export(excel_only=True)` rechecks source/config/results before opening and core `export_to` rechecks after it. Existing other-format export, Extract only and Workflow stay under More actions. Default trial First 10, optional trial copy, explicit sample/full/stale labels.

- [x] Add failing end-to-end tests with real workers: default 10 trial on >10 pages, primary without trial, primary after trial exports ALL selected, valid full results reuse DB, stale settings require new full scan; verify XLSX rows and leading zeros.
- [x] Test chooser cancel, overwritten file preservation on cancellation/failure, source change before continuation, repeated clicks and safe close; substitute only chooser/unavoidable controlled worker failure.
- [x] Implement minimal callback chain; check readiness before opening chooser; don't retain a target or automatic retry across failures/cancel/close. Keep native overwrite/source protection and atomic backend.
- [x] Run both new and legacy GUI modules separately, focused Workflow/core/lifecycle/source contracts, Ruff, source verification and docs links. Full repo suite only if needed by findings; report unrun platforms/native chooser UAT.
- [x] Request independent final read-only review per executing-plans; reproduce material findings RED→GREEN, finish verified local checkpoint and report.
