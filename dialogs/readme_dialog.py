"""In-app feature overview and quick-start guide."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialogButtonBox, QTextEdit, QVBoxLayout

from .base import ToolDialog

README_CONTENT = """# PDFDocuEdit Pro

PDF Editing & Print Production Suite — v3.0.1

**Program Developer:** Andy Leung (andy846@gmail.com)

---

## Overview

PDFDocuEdit Pro combines PDF editing and print-production tools in one main
window. PDF Workspace handles document editing; Document Designer handles
reusable templates, variable data, PDF overlays and Visual Workflow. Documents
and customer data are processed locally. The current production distribution
supports Windows x64.

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
