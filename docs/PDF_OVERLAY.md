# PDF Overlay

Open **Overlay PDFs** from the PDF tools menu. Choose a template PDF, then the current PDF, one PDF, or a folder of PDFs. Choose an output folder and filename suffix. The default `_overlay` suffix preserves the source files.

The preflight table lists each target, page count, output name, and any input or filename conflict. Resolve every issue before applying. A folder can include subfolders; files with the same name may need separate output folders or renamed sources to avoid collisions.

Placement options:

| Setting | Choices and default |
| --- | --- |
| Layer | Above target content (default) or below it |
| Page pairing | Repeat the last template page (default), cycle pages, or match page numbers only |
| Size | Fit within the target page (default) or use the template's original PDF size |
| Position | Nine alignments, rotation by 0/90/180/270°, and X/Y offsets in mm |

Select a target row and page to see the before/after preview. The preview uses the same PDF overlay operation as export. Zoom changes the preview display only. If the current PDF has unsaved edits, the preview and output use those edits. Save the current PDF first to replace it in place.

Batch progress is shown by file and page. Cancel stops before the next page or file; an already completed file remains in the output folder. Each output is written to a temporary PDF, checked, then moved into place. The result dialog shows completed, failed, and skipped files and can export the list as CSV. A failed file does not stop the remaining batch.

The overlay keeps PDF vector content. Opacity control is not currently available in the PDF overlay renderer.
