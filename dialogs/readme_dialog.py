"""Read-only README viewer carried over from the original application."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialogButtonBox, QTextEdit, QVBoxLayout

from .base import ToolDialog

README_CONTENT = """# PDFDocuEdit Pro

**Program Developer:** Andy Leung (andy846@gmail.com)

---

## Overview

PDFDocuEdit Pro is a comprehensive, feature-rich desktop application for
viewing, editing and managing PDF documents on Windows and macOS. It offers
an extensive suite of tools aimed at enhancing productivity and streamlining
workflows involving PDF and other document formats — from fluid viewing and
navigation to advanced batch processing, content extraction, annotation and
security management.

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
  and its subfolders, with contextual previews and CSV export.
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
* **Merge PDFs:** Combine multiple PDF files into one document.
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
