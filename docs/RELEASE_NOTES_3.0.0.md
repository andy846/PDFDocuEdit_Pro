# PDFDocuEdit Pro v3.0.0

PDF Editing & Print Production Suite. This Windows x64 release adds Document Designer and Visual Workflow to the existing PDF Workspace.

## Document Designer

- Switch modes from the main toolbar without discarding tabs, drafts, selection or background jobs. Templates, PDF overlays and workflows use dedicated project tabs.
- Send an edited or unsaved PDF to Designer as a multi-page Mail Merge template background or an overlay source.
- Import CSV, delimited TXT and Excel; map fields, generate sequences and reference values, and preview individual records.
- Design static/mixed/variable text, images, shapes, Code 128, QR and I25 barcodes. Use multiple template pages and structured conditions.
- Edit multiple objects together, with numeric dimensions, rotation, alignment, rulers, snapping and Undo/Redo. Fixed property panels and preserved canvas previews improve editing continuity.
- Windows font selection, per-glyph repairs and automatic missing-glyph fallback retain the primary font and produce repair reports.

## Mailpieces and Visual Workflow

- Text-layer PDF analysis suggests first-page, identifier and page-number rules. Teach-once profiles, paired page review, manual split/merge and explicit acceptance support variable-length mailpieces.
- Reuse Visual Extraction Regions, mapped data and workflow settings across letter templates and batch jobs. Preview/review, composition, media assignment, splitting and reports share structured results.
- Reconciliation, source/page mapping, barcode QC and per-job logs accompany production. A text-only overlay no longer requires a control barcode.
- Template-edit actions open/focus the selected Designer project; a single job does not need an extra picker.

## Media and PostScript

- Assign Stocks by template page, logical page or page role. Preview sheets and duplex pairing; optionally insert blank backs at Stock changes.
- Choose PDF + PostScript without a separate job ticket, or retain PDF + Canon offline JDF.
- Configure paper attributes (MediaType/optional colour and weight) or paper-source positions (MediaPosition). Save/load environment-specific JSON profiles.
- Export a small paper-selection PS proof before production.
- PS files are interpreted to check page count and dimensions before publication. Chinese text and I25 barcode conversion are included in automated acceptance. Split packages rebase file pages and retain global sequences.
- Keep the PDF proof, per-page PS audit, SHA256 and machine-readable job/media reports. Failed/cancelled conversion does not publish a print-ready PS.

## PDF Workspace

Includes existing editing, annotation, Organizer, OCR, Preflight, detailed Deep Search and calibrated ruler features, plus the redesigned Merge PDFs workbench and PDF-to-Designer handoff. Opening Merge preserves the PDF tool sidebar.

## Install / update

New Windows x64 users: use Setup or extract Managed Portable and run Launcher.exe. Existing managed users: Help → Check for Updates → Download Update → Update and Restart. Update ZIP + signed manifest are for managed updates, not first installation.

The updater retains the previous managed version and supports startup rollback. Templates keep their existing format; PS printer profiles use version 2, while version 1 Canon profiles remain readable.

## Limits / validation

- Media/tray behaviour and inserter barcode profiles require actual device specifications and proof prints. Profiles remain Device validation: Pending; no printer was contacted during software acceptance.
- PS requires a PostScript 3 capable controller. Transparency may be flattened at the selected resolution; the PDF remains available for comparison.
- Text-layer detection does not prove document completeness when end/page-number evidence is absent. Uncertain boundaries require review.
- Dynamic flowing tables/overflow, AFP/IPDS, unattended production and enterprise printer submission are outside this release.
- This release supplies Windows x64 artifacts only. See [release validation](RELEASE_VALIDATION_3.0.0.md) for exact tests and packaging evidence.
