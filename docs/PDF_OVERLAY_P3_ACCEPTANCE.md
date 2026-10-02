# PDF envelope overlay — Designer test build

Date: 2026-10-02. Development build; public application version and standard template schema stay unchanged.

## Entry and test steps

1. Open Document Designer and choose **File → PDF envelope overlay…**.
2. Select the existing PDF. Set source pages per envelope, simplex/duplex, sequence start, increment and padding.
3. Inspect the source summary. Incomplete groups and sequence overflow are blocked rather than discarded.
4. Default objects are envelope sequence text and a Code128 control barcode. Drag/resize them over the copied source preview; additional text and QR marks are available under Insert.
5. Select an object to set its page scope. Define required barcode read positions separately. Production rejects any required position without exactly one visible control mark.
6. **Edit barcode payload…** builds an ordered list of fields/literals with numeric widths. Current-page sample is displayed. Default is EnvelopeSeq + two-digit LetterPage + two-digit LetterPageCount.
7. Navigate Envelope/Page, or tick Preview to hide editing outlines. Ctrl+wheel zooms, Space pans, Ctrl+0 fits the page. Fit mode adjusts on window resize; manual zoom is preserved.
8. Save/reopen `.pdcx`; opening this kind from the standard Designer preserves its unsaved template in the original window.
9. Generate PDF into a new job subfolder. Cancel is available in the toolbar while a job runs. Only reconciled, fully decoded output becomes published PDF.
10. Open the PDF/reports from Production results. Reports include envelope/page mapping, exact barcode payload QC, glyph substitutions and job/control summaries.

## Fixed three-page letter example

- Choose the existing 3,000-page source in **PDF envelope overlay** and set **3 source pages per envelope**. This copies each source page once and adds marks; it does not repeat one background for every letter.
- With six-digit numbering starting at 1, envelope 1 uses `000001` on its three pages; envelope 1,000 uses `001000`.
- Default payload tokens produce `0000010103`, `0000010203`, `0000010303` for the first envelope (sequence + two-digit letter page + two-digit source-page count). These are generic example values, not an inserter-specific protocol.
- Simplex: 3,000 output pages / 3,000 sheets. Duplex: four output pages per envelope, including its blank back, for 4,000 output pages / 2,000 sheets. Each next envelope starts on a new sheet.
- If control marks should be on sheet fronts only, set both the barcode object's **Apply to** and job's **Required read positions** to the front-page scope. For first-page-only reading, choose the first-page scope in both controls.
- **Machine control barcode** distinguishes the required control mark from decorative/additional barcodes. Every required position must have exactly one visible control mark; every rendered mark is decoded against its expected value before publication.
- Save the overlay project separately and generate into the chosen output folder. Each job creates a new subfolder containing the production PDF and reconciliation reports.

## What is covered

- Separate workspace, headless engine and QProcess workers. No composition logic added to viewer.py.
- Exact Windows font selection, existing glyph repair policy and multi-selection text formatting are reused.
- Undo/Redo, copy/paste/duplicate/delete; duplicated barcode objects are decorative until explicitly marked as control.
- User-facing errors distinguish composed/verified/failed/unverified envelopes and identify source/output page when available.
- Narrow 960×640 mode hides the dock to keep canvas space. View → Object properties restores it; double-clicking an object also opens it. Envelope/page inputs have reserved widths so their text remains readable at 200% scaling; frozen acceptance checks actual text fit at 960 and 760 pixels.
- Deferred font loading cannot start after a window was closed. Regression covers immediate close before the first event-loop callback.
- Full regression also exposed an existing single-instance socket lifetime fault. `main.py` now connects socket events to QObject slots so deletion disconnects the receiver automatically; a subprocess regression closes 20 routers with pending connections and checks for retained routers or unhandled Qt errors. PDF editor functionality was not rewritten.

## Verified gates

- 286 Composition tests at 200% display scaling: passed, 95.90 s.
- Targeted final UI/standard Designer save/open regression after the navigation width fix: 6 passed, 33.14 s (while full regression/build ran). Earlier run also passed in 9.87 s.
- Entry-point/socket lifetime and overlay UI regression after the minimal router fix: 11 passed, 17.80 s.
- Full project regression at the established standard scale: pending.
- Extra full-suite attempt at 200% offscreen scale exposed fixed-width Viewer/navigation assertions (e.g. a 268 px panel against the existing 300 px assertion) and aborted during failed-window teardown. No assertions or tests were changed. The standard-scale Viewer/entry-point check passed: 15 tests, 31.44 s. New Composition tests and frozen UI acceptance are independently exercised at 200%.
- Windows final frozen acceptance: passed (exit 0), 200% display scaling, after router and navigation-width fixes. Build-carried feature flag worked without an environment override. Existing Designer/editor checks, actual navigation text fit at 960/760 px and both overlay cases passed; 1224 overlay event-loop ticks. Simplex 60 pages / 20 envelopes and duplex 80 pages / 40 sheets / 20 blanks; 120 expected Code128/QR marks decoded in each output.
- Ruff across repository: passed.
- Native 200% GUI acceptance: original-page copy, Code128/QR, save/restore, 60 source pages → 20 envelopes; simplex60 pages and duplex80 pages/40 sheets; 120 decoded marks each. GUI processed 473 timer ticks.
- Earlier frozen acceptance after the deferred-close fix also passed (315 overlay event-loop ticks); the final rebuilt executable was separately validated after the router fix.
- Headless 3,000-page simplex/duplex production and exact final barcode decoding: see PDF_OVERLAY_P2_VALIDATION.md.

## Remaining production gate

This is a general-purpose overlay test build. Inserter brand/model, working control-payload specification and printed samples have not been supplied. The default profile remains **machine validation pending**. Software decoding does not verify reader position, physical feed direction, print scaling, duplex configuration or inserter protocol. Validate these on the actual printer/inserter before a live mailing.

No AFP/IPDS, automatic record grouping by content, variable-length letters, automated continuation or advanced reprint is claimed in this milestone.
