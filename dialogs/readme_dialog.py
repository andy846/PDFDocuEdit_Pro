"""In-app feature overview and quick-start guide."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialogButtonBox, QTextEdit, QVBoxLayout

from .base import ToolDialog

README_CONTENT = """# PDFDocuEdit Pro

PDF Editing & Print Production Suite — v3.0.2

**Program Developer:** Andy Leung (andy846@gmail.com)

---

## Overview

PDFDocuEdit Pro combines PDF editing and print-production tools in one main
window. PDF Workspace handles document editing; Document Designer handles
reusable templates, variable data, PDF overlays and Visual Workflow. Documents
and customer data are processed locally. The current production distribution
supports Windows x64.

## New in v3.0.2

* Conditional Mail Merge processes an ordered list of data files and routes
  records exclusively to different templates. Batch sequences, exception
  review, per-branch approval and reconciliation preserve source identities.
* Template Designer repeats selected fields across pages at exact coordinates
  or equal footer distance; Paste in place preserves position with one Undo.
* PDF measurement uses precise end ticks, paper rulers, draggable guides and
  snapping. Alt temporarily bypasses snapping; guides are not written to PDF.
* Duplex media setup supports repeated Stocks across template pages. Clipped
  merge-field names stay editable without blanking the canvas.
* Inserter I25 — 18 digits uses zero-start group/sheet sequences, physical sheet
  fronts, automatic EOG/check digit, conditional inserts and decoded QC reports.

## Development Update: PDF Production Cleanup

* **Tools → Flatten PDF**: Analyse annotations/form appearances, choose all,
  current or selected pages, then generate a validated new copy. Open-document
  content and its Undo history are retained. Missing appearances and XFA are
  not silently guessed. Searchable text remains unless Rasterise is selected.
* **Tools → PDF Repair / Production Normalise**: Safe Repair rewrites structure;
  Normalise offers explicit removal/flatten/crop options. Maximum Compatibility
  rasterises with a loss confirmation. This cannot repair every broken PDF.
* Choose PDFs for batch processing; each file has its own result and audit.
  Cancel removes unpublished temporary PDFs and retains completed job bundles.
  Optional Production Preflight compares before/after findings.
* PDF Visual Workflow adds **Flatten PDF** and **Repair / Normalise PDF** before
  Extract Regions. Check to this step processes private copies, never approves
  production. Source/config changes invalidate cached results.
* Production filename editors share previews for `{{input.stem}}`, `{{job.id}}`,
  `{{system.date}}` and `{{workflow.sequence|pad:6}}`. Missing values are errors;
  illegal Windows filename characters are sanitised without changing data.
* New PDF workflows use v6; v1–v5 remain readable. Upgrade saved workflows to a
  new file. Old installations cannot read v6 PDF-cleanup nodes. Template,
  Overlay and barcode formats and the public application version are unchanged.
* Namespace/transform syntax currently applies to output naming. Designer text
  continues to save `{{Field_Name}}`; extended barcode/folder/report templates
  are future integrations. No arbitrary Python or shell execution is allowed.
* Digital signature validity cannot survive a derived copy. Encrypted input
  requires encrypted output. Transparency flattening is not offered; coverage
  limits are reported. Rasterisation does not automatically run OCR.

## Quick Start: Two Workspaces

* Use the main-toolbar **PDF Workspace | Document Designer** switch to change
  modes. Switching preserves open tabs, unsaved work and background jobs.
* Use **Send to Designer** from PDF Workspace to turn an edited PDF into either
  a multi-page Mail Merge template background or a PDF Overlay source.
* Mail Merge: import data → place fields/sequences/barcodes → preview records
  → save the `.pdcx` template → Generate Production PDF.
* Finished PDF: Auto Detect Mailpieces → review and accept boundaries → add
  overlay objects → generate and reconcile the result.
* Use **Visual Workflow** to connect compatible steps and reuse settings
  across customer datasets and letter templates.

## Document Designer

Document Designer is the workspace mode. It contains **Template Designer** for
template layout, **PDF Overlay** for finished PDFs, and **Visual Workflow** for
production workflows.

### Template Designer: Templates, Fields and Data
* Start with a blank page or a multi-page PDF background. One customer record
  can produce several fixed template pages; the background remains intact.
* Import CSV, delimited/tab-delimited TXT and Excel data; select import options,
  map source columns and drag fields onto the canvas.
* Add static, variable or mixed text using `{{Field_Name}}`, images, lines,
  rectangles, Code 128, QR Code and I25 (Interleaved 2 of 5) barcodes.
* Generate running sequences and reference values without adding them to the
  imported customer file. Configure sequence starts and increments as needed.
* Use structured conditions for visibility and alternative content. Templates
  and rules do not execute user-provided Python.
* Edit position, size, rotation and text properties numerically; multi-select
  objects to apply common settings. Rulers, snapping and alignment help place
  objects accurately. Undo/Redo preserves editing continuity.
* Select a footer or group of fields, then use **Edit / right-click → Repeat on
  template pages…** to copy to chosen pages at the same coordinates or distance
  from the page bottom. Copies are independent and the entire operation has one
  Undo. **Ctrl+Shift+V (Paste in place)** preserves exact coordinates; objects
  that would extend outside the destination page are rejected without shifting.
* Select installed Windows fonts. Missing-glyph repairs or automatic fallback
  replace unsupported characters while retaining the primary font, with a
  report of affected pages and characters for review.
* Save and reopen templates with field mappings, rules and page settings.
  If a linked source file is missing, locate it before preview or generation.
* Navigate individual records in Preview without generating the whole job.

### PDF Overlay and Mailpiece Detection
* Add text, sequences and inserter barcodes to an existing finished PDF.
  Text-only overlays do not require a control barcode.
* Group mailpieces by fixed page count or use **Auto Detect Mailpieces**.
  Text-layer analysis suggests first-page, identifier and page-number rules.
* Review the proposed boundaries and exceptions before accepting them. Use
  teach-once profiles for recurring layouts and split/merge boundaries when
  needed. Source changes require a new scan and acceptance.
* Production keeps source-page mappings, reconciliation and barcode QC.
  Inserter values and read positions must match the actual machine's spec.

### Inserter I25 — 18 digits
* Select a barcode in Template Designer or PDF Overlay. In **Barcode properties**,
  choose **Inserter I25 — 18 digits**, then **Configure…**. Workflow reuses the
  same template/overlay profile and generation engine.
* **Sequence:** group starts at 00 and cycles through 99 → 00; sheet sequence starts at 00 per envelope.
  Full envelope identity is retained separately from the cycling group digits.
* **Inserts:** six Never / Always / Conditional controls; each group of three
  uses weights 1, 2 and 4. VS1/VS2 output-bin diversion remains Off.
* **Customer info:** nine zeros or an exact nine-digit ASCII data field; leading
  zeros are preserved. Values are never truncated or padded.
* **Placement:** choose Simplex/Duplex without creating Media, or follow active
  Media settings. One mark per physical sheet front; odd duplex envelopes get
  a blank back without a mark. Apply to required template pages at the same
  position with a target-page summary and one Undo.
* **Preview:** segmented payload, barcode image, automatic EOG and check digit.
  Digit 8 is fixed zero. Digit 18 is the modulo-10 complement of the first 17
  digits weighted 3,1 from the left. No extra checksum is appended.
* Generation checks all records and front-side positions before composition,
  then decodes final marks. **barcodes.csv** records full envelope, sheet,
  output page, zero-based barcode sheet sequence, insert masks, EOG, check digit and decode result.
* More than 99 sheets, invalid data, missing or duplicate controls block
  production with record/page/object details. Dimensions, rotation and read
  positions remain subject to actual inserter validation.
* Existing Generic profiles keep their payloads. Current template/overlay
  saves use versions 12/8; fixed Generic layouts use profile v3, while the
  Inserter I25 encoding remains unchanged.

### Generic — Custom Barcode Layout
* Select a barcode → **Configure… → Generic — custom barcode layout**.
  Set **Total length** and add/reorder named segments. Every segment has its
  own Length; the positions and sum are shown and must match Total.
* Choose **Fixed**, **Data field** (imported/mapped CSV, TXT, Excel or Workflow
  extraction values), **System field**, or **Running sequence**. Imported
  fields and system values with the same name stay separate.
* **Numeric:** nonnegative ASCII digits, normalized then zero-padded to Length.
  `000001` becomes `01` in two digits. **Text:** preserve the exact value and
  leading zeros; exact length is required, with no trimming or truncation.
* Running sequences can reference a template sequence or use a barcode-only
  counter: Start 0, Increment 1 by default; per record/envelope, output page,
  or physical sheet within envelope. Duplex faces share a sheet number.
* Overflow stops by default. Explicit **Cycle** is available only for Numeric
  sequences. **barcode-cycles.csv** records full/raw and encoded values with
  record, envelope, page, object, segment and source-row identity. Data fields
  are never cycled or shortened.
* The preview checks available samples, not the entire job. Missing data allows
  saving a structurally valid layout for later configuration; production still
  validates all visible marks in the background before composing any pages.
  Final-PDF decoding and **barcodes.csv** reconcile exact payloads/counts.
* I25 needs an even number of ASCII digits; Code 128 uses printable ASCII;
  use QR for Unicode. Barcode dimensions must support the chosen length.
* Old token profiles require **Convert to fixed-length layout…**. Confirm any
  unknown segment lengths and Total; conversion does not silently rewrite the
  saved profile. Invalid drafts stay available for correction or cancellation.

## Visual Workflow: Settings, Checks and Results

### Build and Configure
* The node library is grouped into **Sources**, **Data preparation**, **Design**
  and **Production output**. Search matches names and function descriptions.
* **Add next step** offers compatible steps and explains unavailable choices.
  Existing PDF/linear Mail Merge recipes retain their current behavior.
* **Create Visual Workflow → Conditional Mail Merge** creates a v5 recipe with
  **For each Data File**, a shared preparation chain, **Batch Sequence** and
  exclusive named template routes. Free cycles and nested loops are not allowed.
* Data steps include field cleaning, field creation, sorting, validation,
  filtering and running sequences. Other steps cover Visual Extraction Regions,
  mailpiece grouping, mappings, letter templates, media and output splitting.
* Select a node to use **Settings | Input | Output | Issues**. Common settings
  can be edited directly; regions, complex rules and media use dedicated editors.
* Draft settings stay with their node when navigating. Invalid drafts show a
  reason and block saving/execution until fixed; applied changes use Undo/Redo.
* Repeated node types retain separate settings, counts, statuses and evidence.

### Check to This Step
* Conditional Mail Merge checks all configured source files. Its shared
  sequence follows file order and each file's filtered/sorted records; exceptions
  reserve their numbers. Refer to the default field as `{{WorkflowSeq}}` in the
  letter template. A conflicting imported/template sequence field is blocked.
* Add named routes with All/Any conditions and choose a saved template per
  route. Exactly one condition must match. An explicit fallback applies only
  when none match; multiple matches always go to **Exceptions**.
* On **Review & approve**, preview a branch record, review exceptions and
  approve selected/all checked branches. Partial production requires explicit
  acknowledgement. **Run approved** produces independent outputs per source
  file and template, with reconciliation CSV, exceptions CSV and a JSON log.
  **Collect Results** collects results and reports; it does not merge PDFs.
* Recheck after data or rules change. Valid completed branches are retained;
  reopening a saved recipe requires a new check and approval, and never resumes
  production automatically. Folder inputs are a fixed snapshot, not a hot folder.
* Select the target node and click **Check to this step**. For Mail Merge,
  explicitly choose one batch job. PDF checks use the current workflow sources.
* Checks process the complete input, even when downstream steps are unfinished.
  Missing input or an incompatible source-to-target path is reported clearly.
* **Input / Output** display 50 rows per page. Press Enter to search, compare
  before/after values and follow original record/envelope/page identities even
  after sorting or filtering. Tables do not load the whole dataset into the UI.
* **Inspect field…** reads any field, including columns outside the compact
  table. Long values are bounded and show a notice when truncated.
* **Issues** identifies the node, source record/page, field and cause. Use
  **Locate source** to inspect the corresponding PDF, record or Designer object.
* Compose/Overlay checks validate the template, data and output plan and can
  preview one record. Output/Reports checks validate configuration. These checks
  do not generate or publish production PDF/PS/JDF/report files or approve jobs.
* Results are temporary and separate from production status. Changing sources
  or upstream settings makes affected results stale; check again before relying
  on them. Editing settings does not automatically rescan large files.
* While a task runs, pan, zoom, select nodes and browse completed evidence.
  Graph edits and repeated execution are locked. Cancellation retains completed
  results. Narrow windows offer **Split view / Steps / Canvas / Details**;
  panel choices and widths are retained during the current session.
* Formal production remains a separate **Review / Run** operation with full
  validation and operator acceptance.

## Print Media, Printer Profiles and PostScript

* Assign logical **Stocks**, rather than hard-coding tray numbers in templates.
  Rules can use template pages, page-in-mailpiece or first/middle/last page roles.
* Open **Page → Print Media / Stocks…** in a Mail Merge template, or
  **Production → Print Media / Stocks…** in PDF Overlay. In Visual Workflow,
  configure the **Media Assignment** node.
* Choose PDF + PostScript (no separate job ticket), or PDF + Canon offline JDF.
  Printer profiles map Stocks to MediaType/paper attributes or MediaPosition.
  Save/load profiles for each environment without changing the logical Stocks.
* Use **Profile library…** to browse device mappings and import profiles.
  Use **Export paper-selection test PS…** for a small proof before production.
* PS output retains a PDF proof, page-level media CSV and machine-readable logs.
  Software checks PS page counts and dimensions before publication; failed or
  cancelled jobs do not publish unfinished production files.
* Tray mappings and DFE queue overrides require an actual printer proof. A
  generic profile is not a verified device preset. PS needs a compatible
  PostScript controller; transparency may be flattened at the chosen resolution.

## Production Summary and Limits

* Generation runs in the background with progress and cancellation at safe
  checkpoints. Inspect input/processed/successful/failed records, expected and
  generated pages, published files, CSV control reports and JSON job logs.
* Reconciliation discrepancies and critical failures are reported explicitly.
  Successful software validation does not replace printer or inserter testing.
* Mailpiece detection uses text-layer evidence. Without reliable page/end
  markers, it cannot prove completeness; uncertain boundaries need review.
* Fixed multi-page templates are supported. Dynamic flowing tables/overflow,
  AFP/IPDS and unattended production are outside the current feature scope.
* v3.0.1 adds node inspection and the local printer-profile library. Use
  Help → Check for Updates in a managed installation to check for releases.

## Key Features

### 1. File Management & Viewing
* **Multi-Format Support:** Open PDF files natively. PostScript (`.ps`,
  `.eps`) files are automatically converted to PDF for viewing.
* **Multi-Document Tabs:** Open several documents in tabs (`Ctrl+Tab`),
  close or rearrange them, and split one document into two side-by-side
  panes (View → Split View).
* **Visual Organizer:** Visually reorder, rotate, delete and extract pages
  in a drag-and-drop interface.
* **Page Layouts:** Single page, continuous scrolling and two-page facing
  layouts, with fit-width, fit-page and actual-size presets.
* **Intuitive Navigation:** Page controls, go-to-page, zoom
  (`Ctrl+ +/-`, `Ctrl+MouseWheel`), hand panning (hold Space) and a
  magnifier tool.
* **Drag & Drop:** Open PDF or PostScript files by dropping them onto the
  window; dropping several files opens several tabs.
* **Detailed PDF Analysis:** Inspect metadata, permissions, fonts
  (usage counts and embedded status), page statistics and image properties.

### 2. Page Manipulation
* **Rotate:** Rotate single pages, custom ranges, or all pages by 90, 180
  or 270 degrees — via the Rotate panel, the bottom-bar quick rotate menu,
  or the thumbnail context menu.
* **Insert:** Insert pages from another PDF at any position or at repeating
  intervals; blank pages of a chosen size are also supported.
* **Delete:** Remove pages using odd/even rules, every-Nth-page rules,
  custom ranges (`e.g. 1, 3, 5-8`) or complex patterns.
* **Extract:** Extract a subset of pages into a new PDF using the same
  powerful selection rules.
* **Split:** Divide a large PDF into smaller files by page count or custom
  ranges.
* **Thumbnail Reordering:** Drag thumbnails in the Pages panel to reorder
  the document directly (undoable).

### 3. Annotation & Content Editing
* **Text Markup:** Highlight, underline, strikethrough and squiggly marks
  follow the selected words.
* **Sticky Notes, Freehand & Shapes:** Add notes, freehand ink and
  rectangle annotations with configurable color and line width.
* **Stamps & Signatures:** 14 standard rubber stamps plus reusable custom
  image and text stamps. Use **Add image…** to import a PNG/JPG, or
  **Add text…** to generate a bordered text stamp; **Remove** deletes it
  from the personal stamp library.
  Signature and general image insertion are also available.
* **Redaction:** Permanently remove sensitive content (with confirmation).
* **Watermarks:** Apply text or image watermarks with opacity, rotation and
  page-range control.
* **Annotation Management:** List and remove annotations per page; every
  annotation step is undoable.

### 4. Search & Data Extraction
* **File Search:** Find PDF files by name across folders and subfolders.
* **In-Document Search (`Ctrl+F`):** Live search panel listing every match
  with context; clicking a result jumps to the page and highlights it.
* **Deep Content Search:** Search the text inside all PDF files in a folder
  and its subfolders, with contextual previews, per-keyword/source filters,
  CSV export and a printable HTML report. Open results at their source pages.
* **Selected Search Pages:** Print or extract selected in-document search pages,
  or send selected pages to Designer without re-entering page numbers.
* **Barcode / QR Code:** Read barcodes and QR codes from one PDF or a whole
  folder at configurable DPI.
* **Extract Text by Position:** Draw a rectangle on a page, then extract the
  text from that region across all pages to Excel or text.

### 5. Batch Processing & Conversion
* **Office to PDF:** Batch convert Word, Excel and PowerPoint files.
  (LibreOffice on macOS, Microsoft Office on Windows.)
* **PostScript to PDF:** Batch convert `.ps` / `.eps` files via Ghostscript.
* **TXT to PDF:** Batch convert text files into individual PDFs or one
  combined document.
* **PDF to Word:** Convert the open PDF into an editable `.docx`.
* **Batch Print:** Print multiple PDFs with printer, paper, orientation,
  margins, copies and duplex settings.
* **PDF Overlay:** Batch overlay a template PDF onto all target files.

### 6. Utilities & Tools
* **Merge PDFs:** Use a dedicated workbench tab to arrange sources, select pages,
  preview and combine them. Open the merged PDF or send it directly to Designer;
  the PDF tool sidebar remains available.
* **PDF Ruler:** Measure page distances in mm/cm with zoom-independent results,
  short dimension ticks and a generous endpoint drag area. Drag and release to
  measure, or click two points. Endpoint drags preserve the grab offset;
  hold Shift for horizontal/vertical alignment. Activating Measure
  shows top/left paper rulers with cursor markers and a reference page; rulers
  follow zoom, scrolling and page rotation, and disappear when leaving the tool.
  Ruler coordinates start at the displayed page's top-left. They show paper size;
  calibrated distances remain on measurement lines. Rulers are not saved to PDF.
  Drag from the top/left ruler to add horizontal/vertical reference guides.
  Alt+drag moves an existing guide; drop outside the page to remove it, or press
  Esc to cancel. Right-click a guide to set its exact position or remove it.
  Click the ruler corner or right-click a ruler to show/hide guides, clear the
  page, or toggle snapping. Measurement endpoints snap within 8 screen pixels
  to guides/page edges; hold Alt to bypass snapping and Shift to constrain axes.
  Guides remain in the current workspace and are cleared on document reload;
  they are never written to PDF or added to PDF Undo/Redo history.
  Calibrate page scale and save measurement lines as PDF annotations.
* **Inspector / Preflight:** Check fonts, images, page boxes and production
  warnings; jump to affected pages and export findings.
* **Merge CSV/Excel:** Merge data from many spreadsheet files into one
  master file.
* **PDF Compression:** Reduce file sizes with several compression levels.
* **Page Count Report:** Generate an Excel report for all PDFs in a folder.

### 7. Security
* **Encrypt PDF:** Protect files with AES-256 password encryption and
  granular permissions.
* **Decrypt PDF:** Remove password protection.

## Editing Model

Edits such as deleting, inserting, rotating, annotating or reordering pages
are performed on a working copy. Use `File → Save` (`Ctrl+S`) or `Save As`
to make changes permanent. Every edit can be undone (`Ctrl+Z`) or redone
(`Ctrl+Y`); the Edit → Undo History window jumps to any earlier state.

## Support

For questions, bug reports, or technical support, please contact Andy Leung
at: **andy846@gmail.com**

---

Thank you for using PDFDocuEdit Pro!
"""


class ReadmeDialog(ToolDialog):
    def __init__(self, parent=None):
        super().__init__("README", "readme", parent)
        self.resize(860, 640)
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(README_CONTENT)
        self.text_edit.setReadOnly(True)
        layout = QVBoxLayout()
        layout.addWidget(self.text_edit)
        self._root.addLayout(layout)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._root.addWidget(buttons)
