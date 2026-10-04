# Visual Extraction Region / Workflow delivery

This is an implementation and verification record, not a v3.0 release announcement.
The existing Composition development flag controls the new workspace. Public version remains unchanged.

## Entry and first job

- From PDF Workspace: the main toolbar's **More** menu → **Visual extraction workflow…**, or search for that command with **Ctrl+K**.
- From Document Designer: **Workspace → New visual extraction workflow**, or the Designer start page.
- Workflows are separate Designer project tabs. PDF/template/overlay tabs remain open when switching.

1. Select **PDF Input**, add PDFs or **Add current workspace PDF** to capture unsaved edits. Unapplied form drafts require Apply / Send without draft / Cancel. Adding multiple PDFs inserts and connects a Merge node automatically; source order is editable.
2. Select **Extract Regions → Edit visual extraction regions…**. Draw named boxes, change exact mm coordinates, select first/all/role scopes and configure text cleanup/required/format/length checks. Click an existing box to select; drag its body to move, or bottom-right corner to resize. Region edits have Undo/Redo.
3. Select **Group Mailpieces**: fixed pages, extracted-field changes, or a literal printed page-number pattern such as `Page {CURRENT} of {TOTAL}`. Apply settings.
4. **Run to review**. Results retain raw text and cleaned values. **Previous finding / Next finding** jumps to an affected page. **View PDF region** opens that page for checking. Correct a page value with a reason; envelope values are rebuilt. Merge/split adjacent boundaries if necessary.
5. **Accept review** requires zero unresolved applicable findings. Optional fields can be configured as optional before rescanning; first-page scopes do not demand values on continuation pages.
6. For overlay, use **Create / edit in Designer…**, choose a `.pdcx` location, add objects, then save the overlay. The field list and Barcode payload profile include `Page_Account_No` and `Envelope_Account_No` etc. Preview receives the workflow's disk-backed values for the requested envelope/page. Return to the Workflow tab to generate; standalone generation of external-data overlays is disabled. An open overlay with unsaved changes or invalid drafts blocks Workflow production rather than silently using an older saved layout.
7. Select **Validate & Output**, choose a folder and **Generate production PDF**. With no overlay objects, generation still validates/copies/reconciles the PDF without requiring a barcode. An optional Overlay node can be removed entirely.

## Canvas and data contracts

- Native Qt canvas: draggable nodes, ports, connections, arrows, pan, Ctrl+wheel zoom, Fit flow, settings/status summaries. Drag tools from the toolbox, or double-click them. The toolbox collapses at narrow widths; **Add step** remains available and inserts/connects optional Merge/Overlay steps. Settings include **Connect to next…**; Escape cancels a pending port connection. Incompatible connections, branches, cycles and duplicate tool types are rejected.
- The chain is Input → optional Merge → Extract → Group → Review → optional Overlay → Output. Running to a selected node and running to review use the same executor. Review always stops unattended progression until accepted.
- `workflow/model.py`: versioned `WorkflowSpec`, `WorkflowNode`, `WorkflowRun`. Canvas positions are excluded from execution fingerprints.
- `workflow/extraction.py`: `Region`, `ExtractionSpec`, `ExtractionResult`, `ExtractionStore`. Visible-page mm coordinates are transformed for PDF rotation/CropBox. Fixed regions reject mismatched reference geometry rather than scaling silently. Text is never converted to a number, preserving zeros.
- `workflow/engine.py`: `execute(spec, run, directory, until=..., progress=..., is_cancelled=...)`. No Qt or Editor objects. Each step has an input/settings signature. Updating overlay/output settings preserves extraction/group data; changing source/extraction/group settings invalidates approval. Source/template bytes are rechecked before production.
- SQLite stores page cells, applicability, envelope values, original source-page provenance, corrections and boundary corrections. Tables fetch one requested page; envelope lists use an item model. Preview raster size adapts to zoom/device scaling, capped at 4096 pixels, with one current preview worker and discarded image files.
- Page and envelope fields have explicit `Page_` / `Envelope_` namespaces. Envelope values either take the first applicable page or require applicable pages to agree. Missing/invalid grouping fields never produce an inferred boundary.
- Overlay schema is **5**, adding a validated `external_fields` list; versions 1–4 migrate. Older builds cannot read new version-5 projects. Tests formerly asserting current schema 4 now assert 5; the future-version rejection fixture moved from 5 to 6. No test was disabled.
- `generate(..., external_values=..., additional_reports=...)` adds optional headless data/report services to the existing overlay generator. Reports finish inside staging before publication. Existing callers require no change.

## Saving, output and lifecycle

- `.pdflow` is JSON schema 1; `.assets` contains hash-checked PDF snapshots and copied overlay/font/image assets using existing licensed font handling. Save/load, missing-source location and same-path focus are supported. Reopening restores configuration; it does not restart jobs or silently trust previous approval.
- UI operations run through the existing isolated composition worker process. Each worker owns its own PDF/SQLite connection. Switching modes does not cancel jobs. Closing/exiting confirms unsaved edits first, then cooperatively cancels and waits for safe cleanup. Preview requests may be superseded; publishing tasks are not killed.
- Job outputs include existing PDF, page/envelope/barcode/control reports and `job.json`, plus `extracted-data.csv`, `workflow-page-map.csv`, and `workflow.json` with configuration/fingerprint/correction audit. Temporary `run.json` records step state. No source is overwritten.
- Source-page mapping follows selected Merge pages to their original file/page. Inserted blank backs have no original source. Output page mapping is generated from the same EnvelopePlan used for production.
- Imported CSV-report values are escaped as spreadsheet text where they could otherwise execute formulas. Rules remain declarative; no Python eval, shell execution or custom code node is available.

## Focused verification

- New core/UI cases cover Chinese text, leading zeros, raw values, rotation/CropBox, geometry mismatch, scopes/consistency, correction audit, valid/invalid graphs, actual Merge provenance, issue navigation, manual boundaries, cancellation/staged-file cleanup, missing text, source changes, review gate, no-barcode production and real extracted-field Barcode decoding.
- UI cases cover native worker responsiveness, save/open/same-path focus, mode/shortcut routing, cancelled close, background cancel across mode switching, narrow light/dark layout, region Undo and retaining the background on region edits. New cases were exercised at 200% scaling. Core import is also checked in a fresh process without Qt.
- Related existing overlay models/engine, handoff, layout geometry, workspace modes and workspace handoff tests: **90 passed**. New feature cases: **25 passed**; related CI selection cases: **8 passed**. Ruff and `git diff --check` passed. Full regression/Windows installer verification remains deferred as requested.
- Offscreen snapshots with a registered Windows UI font were inspected. This found and corrected dark-toolbar contrast and region-property horizontal clipping. Offscreen checks are not a substitute for operator testing on the actual desktop.

### Benchmark

`python scripts/workflow_benchmark.py --pages 1000 10000` creates fixtures and runs each job in a fresh process. It records generation time, pages/second, working-set peak and output size. The current one-run warm-cache results:

| Text pages | Envelopes | Extract + group | Production | Total | Main process peak | PDF bytes |
|---:|---:|---:|---:|---:|---:|---:|
| 1,000 | 334 | 0.295 s | 0.968 s | 1.264 s | 81.8 MiB | 412,436 |
| 10,000 | 3,334 | 2.493 s | 7.745 s | 10.238 s | 98.9 MiB | 4,207,669 |

Fixtures are local A4 text pages, one region, variable groups of up to three pages, **no overlay objects/barcodes**. Main-process peak excludes the qpdf child; existing job reports retain assembler measurements. These are not medians or guarantees for image-heavy, UNC or real production workloads. Large benchmarks are not added to ordinary CI runs.

### Actual sample

The provided `C:\Users\andy8\OneDrive\桌面\sample\merged.pdf` was inspected read-only: **2,497 pages**, uniform A4, all pages with text. A region based on the first text block produced 2,435 nonempty page values and 62 findings. The source hash stayed unchanged. No `Page n of n` English pattern was detected. Correct mailpiece ranges were not supplied, so grouping accuracy and inserter readiness have **not** been certified for that sample. Sample data/results are ignored local QA artifacts, not committed fixtures.

## First-release limits

One linear workflow, one instance of each supported step; no branches, loops, scheduler, automatic resume, OCR or text anchors. General first-page markers/separator rules and arbitrary detection-rule combinations remain available in the existing overlay detection dialog; this first canvas exposes fixed/field-change/page-pattern grouping. Production retains the overlay engine's uniform page-geometry restriction. Inserter compatibility still requires the actual machine specification and testing.


## Consolidation — 2026-10-03

### Settings and navigation

- Grouping, output folder and per-source Merge page settings are tracked as drafts. Switching nodes, saving, running or closing applies them first. Drafts show the unsaved marker; Undo/Redo follows the actual history rather than being enabled by background-worker cleanup.
- Merge source selection retains the page setting for the previous source. A missing grouping-field name remains visible as missing instead of silently selecting another field. Irrelevant grouping options are disabled.
- Multiple-source input automatically inserts a connected Merge step in the same undo operation. The compact **Add step** menu remains visible at 960-pixel widths. Wide toolbars label Scan & review / Generate PDF; idle Cancel is hidden.
- Review rows retain their source-page identity. Corrections are blocked while displayed fields belong to a different requested page. Navigating pages keeps the corresponding envelope and selected field highlighted.

### Data, retry and output consistency

- Boundary edits reach the on-screen model only after successful database commit. Corrections, regrouping and audit entries share one transaction; cancellation or failure rolls the mutation back.
- A grouping failure still permits correcting extracted page data, then retrying Group without rescanning the PDF. Acceptance requires complete grouping; production compares the run's boundaries to the accepted database boundaries.
- Missing inputs become logged node failures. A missing downstream overlay does not prevent input extraction/review. Missing/corrupt extraction caches or changed owned snapshots rebuild and require fresh review. Owned source snapshots are replaced atomically, so retries and changed-source scans work without deleting the source PDF.
- Starting a new production attempt clears the previous result from the active run. Worker failures no longer leave nodes labelled Running or show an older completed PDF as the new result.
- Reopening an overlay from Workflow synchronises its PDF source, extracted fields and envelope groups as an undoable edit. Objects, fonts, barcode profiles and sequence options are retained. Save the changed project before Workflow production. Preview and barcode sample dialogs reject stale source/group bindings.
- CSV adds a **Scope** column and envelope rows, including envelope-consistency findings. Existing column names remain available. CSV export cannot overwrite the database or original source PDFs. Hash-named overlay source assets are verified before reuse.

### Region editor

- PDF rendering remains available while a region draft is invalid, so the operator can see and repair its geometry/name. Production validation remains strict.
- New default regions adopt and fit the actual first PDF page, including small/non-A4 pages. Existing region positions are retained. **Use this page size** explicitly changes reference dimensions without scaling coordinates.
- The entire property sidebar scrolls in short/high-DPI windows. Field names have a usable minimum width, duplicated names remain bounded, and keyboard Undo/Redo is available.
- 960×640 / 200% offscreen snapshots were inspected in light and dark modes. These checks supplement operator testing on the real desktop.

Consolidation verification: **57 passed in 45.56 seconds** at 200% scaling (44 Workflow core/UI cases plus 13 directly related existing overlay, optional-barcode and mode/close cases). Ruff and whitespace checks passed. No existing test was disabled. Historical benchmark numbers above have not been rerun and are not new performance measurements. Full regression and packaging remain deferred as requested.
