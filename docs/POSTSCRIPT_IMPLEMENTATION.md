# PostScript production output — implementation note

The existing headless MediaSpec / PrintPlan already provides final physical page, sheet, side and Stock mappings. Keep it as the single source of pagination truth, including blank backs and split-output rebasing.

## Changes

- Extend PrinterProfile with version 2, a PostScript backend, declarative attribute/tray mappings, duplex binding and conversion resolution. Continue reading existing version 1 Canon JDF profiles unchanged.
- Add `composition/media/postscript.py`: use the existing Ghostscript capability and bundled ps2write device; generate DSC output, stream in validated page instructions and audit rows, then interpret the PS to a temporary PDF to verify page count and dimensions. Python must not hold all PS pages in memory.
- Emit selection commands on physical sheet fronts; backs inherit the front Stock. Keep application pagination and blank insertion authoritative. Printer profiles contain data, never arbitrary PS or shell snippets.
- Extend media package reporting to distinguish PDF + JDF from PDF + PS. Add PS generation before normal/overlay atomic publication and after per-file split rebasing. Keep the validated PDF alongside PS for review. Failed/cancelled packages must not publish PS.
- Generalise the existing Media dialog's printer tab with output format, selection method, binding, resolution and per-Stock mapping fields. Reuse JSON profile save/load and background workers. Add a small paper-selection PS test export.

No editor rewrite, public version change, new converter dependency or printer submission is needed. Existing Ghostscript packaging/licensing remains the existing project's responsibility; this change adds no distribution of third-party files. Actual tray/media behaviour remains a device acceptance check, and profiles are labelled unverified until the user's sample/proof is available.

## Targeted gates

Version 1 roundtrip, invalid mappings and escaped strings; real GS PS conversion and interpretation; Unicode/visual/barcode output; attribute/tray requests; simplex/duplex blanks; cancellation and failed-publication cleanup; template and overlay end-to-end; rebased split packages; dialog configuration/profile roundtrip, narrow layout and paper test. Retain the user's deferred full regression / Windows packaging arrangement.

References: Ghostscript ps2write ProduceDSC documentation (`https://ghostscript.readthedocs.io/en/gs10.05.1/VectorDevices.html`), Adobe PLRM device selection (`https://www.adobe.com/jp/print/postscript/pdfs/PLRM.pdf`), Canon varioPRINT media selection documentation. ps2write writes level 2 page content; injected MediaPosition/duplex selection requires a PS level 3 capable target. Transparency can require flattening; the PDF is retained for comparison and conversion resolution is explicit.

## Verification — 2026-10-05

- The five targeted Media / PS / review modules passed 69 tests together. After adding converter failure and percent-containing output-directory cases, all 29 PS core tests passed.
- Real Ghostscript generation and interpretation covered both attribute and tray requests, simplex and duplex blank backs, overlays and Workflow split packages. A Chinese text + I25 case compared rendered ink and decoded the interpreted barcode.
- Converter unavailability fails before composing records; conversion failure and late cancellation leave no published PDF/PS. Subprocess cancellation terminates the owned converter.
- Qt profile roundtrips, backend switching, background paper proof and production summaries passed. Offscreen screenshots were inspected for light/dark layouts at 960×640, with both 100% and 200% device scaling. User settings/projects and the running application were untouched.
- Ruff and whitespace checks passed. Full application regression, installer packaging and hardware printer acceptance are deferred under the user's existing instructions.

Usage: [PostScript / profile guide](POSTSCRIPT_USER_GUIDE.md).
