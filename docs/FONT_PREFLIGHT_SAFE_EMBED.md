# Font Preflight / Safe Embed Fonts — development feature

## Editor workflow

Open a PDF in PDF Workspace. Use **Tools → Font Preflight / Safe Embed Fonts…** or the left **Utilities** entry.

1. **Analyze fonts** is read-only. Check status, coverage, referenced pages, and reasons.
2. Double-click a font row to visit its first referenced page in the originating Editor tab.
3. Select a row and **Choose original font…**. **Find installed candidates…** lists exact PostScript-name candidates only; it never automatically accepts a font.
4. Confirm authorized embedding rights and **Check sources**.
5. Choose the authoritative original-font **Reference PDF**, confirm its origin, then **Repair Copy…**.
6. A new job folder is published only after successful validation. It contains the PDF and JSON/CSV audit. Existing PDFs and open Editor Undo state are unchanged.

**Choose PDFs…** scans a batch with independent file outcomes. Select a file and **Inspect selected batch PDF** to review its resources and configure its original fonts; return to the batch results without rescanning. The headless `repair_batch()` API requires explicit source/font/reference configuration per file; the UI does not automatically borrow settings or font xrefs between files.

## Supported safe repair — deliberately narrow

Static, complete TrueType programs, simple WinAnsi font dictionaries, a valid indirect FontDescriptor, exact PostScript identity and compatible stored widths. Width checks permit only rounding to half of one PDF 1/1000-em width unit; original PDF Widths are never changed. No subsetting is performed; no-subsetting flags are respected by full-program embedding.

A reference must contain the **same actual font binary** (SHA256), unchanged original objects/content, and stable object identities. Thus a separately recreated/renumbered reference PDF can be rejected even if it looks similar. A family-name match or the current screen using an unknown substitute is insufficient proof. No customer reference means inspection remains useful, but automatic repair stays blocked.

Type0/CID/CJK, Type1/CFF, Type3, custom encodings, subset names, TTC/variable/colour faces and ambiguous/shared descriptors are not safe-repair targets in this implementation. They are inventoried where traversal is supported. Uninspectable structures invalidate scan completeness. A present font stream is not certification of the embedded binary's correctness. Text invocation is not inferred: referenced resources may be unused.

Base-14 is exempt under Print policy; Strict policy reports its embedding requirement. Neither policy claims complete PDF/A compliance. veraPDF remains the application's separate standards-validation service.

Encrypted/restricted and digitally signed/certified PDFs are scan-only. The Editor retains this restriction even when it creates an unencrypted working snapshot. Handwritten signature images are not treated as cryptographic signatures.

## Preservation, QC and failure handling

Only a new full FontFile2 stream and its FontDescriptor reference are written. No content operators, Encoding, Widths, ToUnicode, paths, annotations, form values, images, page boxes or rotations are recomposed. All original objects and raw streams are compared; expected font programs are re-read and hashed independently. qpdf must return OK, followed by complete output inventory and exact 300-dpi tiled pixel equality against the trusted reference on every page.

The service owns its own documents inside the existing isolated authenticated PDF worker process. Fonts and PDF resources have size/nesting/traversal limits. Cancellation checks run between resources, pages and tiles; it cannot interrupt an individual native rendering/save call. Metadata cache and font/verification stream inputs are limited to 64 MB; the process also uses MuPDF memory, so this is not a guarantee of a 64 MB process limit. No whole-document conversion, fallback font substitution, rasterisation, or text replacement is used.

Sources, fonts and references are fingerprinted; changed inputs invalidate approval. Cancellation/failure cleans unpublished PDFs. Completed batch jobs remain. Each repair job records success or a metadata-only failure/cancellation audit; inability to write a failure report is surfaced by the original error. Reports omit font binaries, passwords, customer page text and source paths by default. CSV values are protected against formula injection.

## Architecture / compatibility

`core/font_preflight/`: models, bounded PDF object reader, inventory, exact matching, validator, service and existing-worker dispatcher. `dialogs/font_preflight.py`: UI adapter. Reuses core atomic I/O, PDF reopen/qpdf checks, worker transport and OS font discovery. No dependency, project-format, public-version or update-key change. Existing Designer glyph-repair semantics are unchanged.

Standalone inspection and supported native writer are implemented. Visual Workflow nodes remain gated on real customer acceptance; no workflow schema is changed. Mac test lists include this feature, but native macOS packaging/manual testing is still required before release.

## Reproducible evidence

Focused tests generate their own simple TrueType font with fontTools and synthetic PDFs; no licensed/customer font assets are committed. Run `python -m pytest tests/test_font_preflight.py tests/test_font_preflight_ui.py`.

Run `python -m scripts.benchmark_font_preflight` for isolated 1k / 20k-page scans. Results include duration, throughput, peak process memory and fixture limitations. The synthetic shared Base-14 fixture does not predict scan/repair speed on network, image-heavy, appearance-heavy or CJK customer PDFs.


### Local development measurements (2026-10-11)

Windows isolated synthetic scans: 1,000 pages in 0.1400 s (peak process memory 66.43 MB); 20,000 pages in 3.0798 s (122.72 MB). Peak includes fixture construction and interpreter/runtime allocations, not only the inventory service. These are single-run synthetic observations, not a production performance guarantee or a before/after baseline. Repeat the benchmark for comparative medians before release.

Focused regression: 80 tests passed across new inventory/native-repair/UI cases, existing font inspection, PDF operations/normalise/batch, Designer system fonts/glyph repairs/UI, workflow cleanup, and task lifecycle. Ruff and whitespace checks passed. Dark/light offscreen layouts were inspected using an explicitly loaded installed UI font; large-font/narrow-window footer tests passed. No native macOS build or full release regression has been performed for this development feature.
