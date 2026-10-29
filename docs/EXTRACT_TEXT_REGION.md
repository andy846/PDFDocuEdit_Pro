# Extract Text Region 2.0

The PDF Workspace extraction command opens the shared visual region editor on
a frozen copy of the current PDF. Applied, unsaved edits are included; an
unapplied form draft requires an explicit Apply / Extract without draft choice.
The original PDF is never used as an extraction output destination.

## Operator workflow

1. The Quick tool starts without a default region. Click **New region**, then
   drag on the PDF; release to create the field and return to selection mode.
   Esc cancels drawing without closing the tool. Each region becomes **one column**.
   Drag inside a region to move it; drag its lower-right corner to resize it.
   Millimetre controls, Undo/Redo, Ctrl+wheel zoom and Space-to-pan remain available.
2. Choose all, current or custom source pages. Preview the selected field's Raw
   and Clean text. `Join lines with spaces` is on by default; turn it off to retain
   line breaks inside the same cell. Raw text always retains the extracted layout.
3. Optionally use **Try 10 pages** to check the fields. First 10 is the default;
   first 50, random 50 and all selected are also available. Every trial remains
   labelled Sample and cannot be exported as complete results, even when its
   sample happens to include every selected page.
4. Use **Extract & Export Excel…** for the normal workflow. It fully extracts
   the selected page range, loads the result table, then opens the Excel save
   chooser. A current complete extraction is reused; a trial or stale extraction
   is scanned again. No trial or separate Extract click is required.
5. For a separate review before saving, choose **More → Extract only**, inspect
   the table, then use the main Excel action. **More → Export complete results…**
   retains XLSX, CSV and tab-delimited TXT. Results show up to 100 rows at a time;
   every selected source page keeps a row, including no-text, empty-required-field,
   invalid-format and geometry-mismatch pages. Field issues remain exportable;
   invalid configuration, stale source/results and unsupported output
   representations still block export.

## Portrait-first workbench

The PDF occupies the full-height left pane, using approximately 48% of the width
initially. A portrait A4 page retains its proportions and no longer shares its
height with the results table. Fields/properties occupy the top-right; results,
trial/page-range controls and export actions remain on the right. Landscape and
other page shapes still use the existing fit/zoom/pan controls without stretching.
First use occupies about 92% of the current screen's available area.
Window size, maximized state, panel proportions and sidebar visibility are
remembered locally, without saving document data or extraction regions. A moved
or removed screen is bounded to the available screen on reopening and on screen
or DPI changes. Properties are initially visible; Fields and Properties can be
toggled from the toolbar. The new layout imports only window geometry from the
earlier layout, never its incompatible splitter axes or collapsed state.

Drag the main divider to adjust PDF/results width and the right-side horizontal
divider to allocate space to settings/results. **Expand**
temporarily uses the workspace for the table; **Restore** restores its
previous splits. **Hide table** hides the table without losing its data.
At 1280×800 the default table accommodates at least eight complete rows, and at
960×640 at least six, including a horizontal scrollbar for many fields. The
minimum visible-row allocation can take more of the right pane in a short window.

List entries and PDF badges share the output-order number and field name.
Select either to activate a region: the active frame is thicker and has a
lower-right resize handle; other frames are dashed. Clear **All regions** to
show only the active one. An active overlapping field keeps priority; right-click
inside overlapping rectangles to choose a field by name. Long names have full
tooltips. Duplicate keeps dimensions and offsets by up to 5 mm within the page,
trying the reverse direction at the far edge. A whole-page field may overlap.
Quick Extraction can delete its final field; extraction is disabled until a new
field is drawn. The existing Workflow editor retains its original default field.

Common field settings appear in **Properties**; millimetre geometry, reference page
size, label removal and length rules are under **Position / size / advanced rules**.
**Text preview** shows the active field's Raw
and Clean text. Clicking a current result row navigates to its source page;
clicking a named result column also selects its field. This includes sample
results, which still cannot be exported. Viewing pages in All/Custom mode,
selecting fields and changing layout do not invalidate extraction. Current
preview page mode, real field/rule edits or a changed source require extraction
again. Drawing waits until the displayed raster matches the chosen source page.
The results heading distinguishes Sample, Complete, Out of date and failed or
cancelled checks. Cancellation/failure/close do not continue to the save chooser;
cancelling the chooser retains the complete results for a later save. Source and
configuration are checked again after choosing a destination. The main Excel
action requires `.xlsx`; other formats remain in More. Existing overwrite
confirmation and atomic output publication are unchanged.

Different page sizes are **not automatically scaled**. Region coordinates are
millimetres from the visible page's top-left, using the existing rotation and
CropBox conversion. A geometry mismatch needs an appropriate new extraction
setup. Image-only pages require a separate OCR step; this tool does not add OCR.

Field names use the existing Workflow format: letters, digits and underscores,
starting with a letter/underscore, up to 64 characters. Up to 200 regions are
supported. No extraction Profile or Profile Library is created.

## Output and integrity

- XLSX contains `Data`, `Details` (Raw/Clean/status/issue) and `Issues` sheets.
  Text values are explicitly typed as text, including leading zeros, long
  identifiers and strings beginning with `=`. The workbook description identifies
  the job snapshot SHA256; extraction is not production authorization.
- XLSX values exceeding its character/XML/row limits are rejected, rather than
  silently truncated. CSV or TXT can represent longer values.
- CSV contains named value, Raw, status and issue columns in a single file.
  Potential spreadsheet formulas, including after leading whitespace, receive a
  protective apostrophe. This does not alter the SQLite Raw/Clean evidence.
  Excel may infer numeric types when opening CSV: import identifiers as Text,
  or use XLSX when zeros and long identifiers must be preserved automatically.
- TXT is UTF-8 tab-delimited, with quoting for multiline values, using the same
  structured columns. The legacy single-region `core.tools.extract_region_text`
  entry and its original TXT output remain available to existing callers.
- Each output is staged in the destination directory and atomically published.
  Existing files need explicit overwrite confirmation. Source PDFs, protected
  original paths and the job database cannot be overwritten, including aliases.
- Cancellation or failure before publication preserves the previous output.
  A committed export remains reported as completed if cancellation arrives late.
  Closing waits for workers before releasing the job snapshot, SQLite and previews.
  A superseded or closing non-publishing preview may be stopped through the
  existing isolated-worker mechanism, including a blocked native raster call;
  scan/export workers retain cooperative cancellation and atomic publication.
  Temporary cleanup errors are shown and Close can retry.

These checks detect missing text layers and field problems; they do not certify
that extracted text matches the document's business meaning or reading order.
Preview panels shorten very long values for responsiveness and label this;
the full values remain in the job store and supported exports.

## Visual Workflow handoff

`Open in Visual Workflow` copies the **same frozen snapshot** into the new
Workflow's owned directory, with the current regions. Selected pages use the
existing Merge selection node, preserving source-page provenance. Closing Quick
Extraction cannot invalidate that copied source.

The Workflow starts without accepted extraction results or production approval.
Run it, review grouping and data, and complete existing production checks before
output. No `.pdflow` schema or production authorization rules were changed.

## Implementation and validation

- Shared semantics: `workflow.extraction.Region`, `ExtractionSpec`, `extract_page`.
- Shared editing: `workflow.regions_ui.RegionEditor` / `RegionCanvas` and the
  existing `composition.designer.process.Worker` transport/admission gate.
- Quick-only SQLite, selected-page scan and atomic export: `core/text_extraction.py`.
- Editor snapshot/lifecycle/handoff: `ui/text_extraction_controller.py` and the
  existing main-window close lifecycle.
- Quick-only workbench/presentation: `dialogs/extraction_workbench.py` and
  `dialogs/extraction_canvas.py`, using the same Region/ExtractionSpec model.
- Compatibility: no public version bump, new dependency, Profile format, PDF
  processing engine change or production-authorization change.

See [verification record](EXTRACT_TEXT_REGION_VALIDATION.md) for measured synthetic
workloads, automated coverage and manual UAT limitations.
