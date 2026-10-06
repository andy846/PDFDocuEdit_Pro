# PDFDocuEdit Pro v3.0.1

Windows x64 update for Visual Workflow, print-media profiles and in-app help.

## Visual Workflow: settings and evidence

- Select a node to inspect **Settings | Input | Output | Issues**. Common data
  settings are editable inline; regions, rules and media retain dedicated editors.
- **Check to this step** processes the complete source-to-target path, including
  workflows with unfinished downstream steps. Mail Merge requires an explicit
  batch-job selection.
- Input/Output fetch 50 rows per page, support Enter-to-search, preserve original
  source identities and compare before/after values. **Inspect field…** reads any
  column, including values outside the compact table.
- Issues identify the node, record/page, field and reason, with source/Designer
  navigation. Repeated node types now keep independent status and evidence.
- Checks validate template/data/output plans and support a one-record scratch
  preview. They do not publish production output or approve jobs.
- Changed sources/upstream settings invalidate affected evidence. Cancellation
  retains completed results. Invalid settings drafts survive node switches and
  block save/run until repaired; applied edits use Undo/Redo.
- Running tasks allow canvas pan/zoom, node selection and result browsing while
  graph edits and repeated execution remain locked. Incremental scene updates
  preserve the current view.
- Categorized node library, description search, compatible **Add next step**
  choices and narrow-window **Split view / Steps / Canvas / Details** layouts.
  Panel choices and widths remain available throughout the session.
- Workflow versions 1–4 remain readable; v4 media review uses the shared pipeline.

## Printer profiles and help

- **Profile library…** browses local device mappings, previews media settings and
  loads JSON/files/folders in the background. Cancelled loads preserve drafts.
- Media summaries show the selected PS/JDF backend, Stocks and duplex settings.
  Existing paper-selection test PS export remains available.
- **Help → README** now covers Document Designer, multi-page Mail Merge,
  sequences, barcodes, PDF overlay, mailpiece review, step inspection, Stocks and
  PostScript, including the relevant entry points.

## Install / update

New users: download Setup or Managed Portable and start via Launcher.exe.
Existing managed users: **Help → Check for Updates → Download Update → Update and
Restart**. Update ZIP and signed manifest are for existing managed installations.
Downloads include SHA-256 checksums. User projects retain their existing formats.

## Limits

Step checks do not replace final composition/barcode QC or operator approval.
Table/field displays are bounded; processing and validation use the complete input.
Results are temporary; no automatic restart/resume is introduced. Workflows remain
linear. Printer tray mappings and inserter controls require actual device proof;
no printer has been contacted by automated software tests. This release provides
Windows x64 artifacts only.

See [release validation](RELEASE_VALIDATION_3.0.1.md) for release-gate evidence.
