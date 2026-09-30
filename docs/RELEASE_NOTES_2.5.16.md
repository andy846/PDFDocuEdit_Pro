# PDFDocuEdit Pro v2.5.16

This release improves Deep Search results and exports, and adds page-scale calibration to the PDF ruler.

## Deep Search

- Count and inspect every occurrence of each search term, with its page, source (text or barcode), and surrounding context. Search progress updates by page; cancellation retains completed files and marks the run incomplete.
- Filter results by file, keyword, and source. Open a matching PDF directly at the selected page when using the built-in viewer.
- Export a styled, self-contained HTML report with a summary, per-file matches, and file errors. CSV contains one row per occurrence or error for analysis. Export all results or the current filters. TXT remains available.
- Large result sets use paged display and disk-backed storage; report exports run in the background. Image-only pages still require OCR before text search.

## PDF ruler

- Calibrate the real-world scale independently for each PDF page. Saved measurements and their labels update together when a page is recalibrated.
- Reopen and edit saved ruler endpoints; changes participate in Undo and Redo. Existing older ruler annotations remain intact.
- Measurements retain their page coordinates through rotation and page operations. Read-only comparison panes can inspect measurements without modifying them.

## Install or update

For a new Windows x64 installation, run `PDFDocuEdit-Pro-v2.5.16-Setup-Windows-x64.exe` or extract the Managed Portable ZIP and start `Launcher.exe`. Existing managed installations can use Help > Check for Updates > Download Update > Update and Restart.

The signed update ZIP and manifest are for existing managed installations. SHA-256 files are provided for the installer and both ZIP packages. The Setup EXE is not Authenticode-signed; verify its SHA-256 checksum.
