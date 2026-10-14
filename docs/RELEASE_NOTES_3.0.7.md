# PDFDocuEdit Pro v3.0.7

## PDF Workspace reliability

- Reopening an already-open PDF focuses its existing tab or document window and clears only the opening queue's activity. Dirty edits and Undo remain intact; another task's progress is not hidden.
- Operation-error recovery preserves owned canvas/thumbnail readers until safe retirement and rebinds consumers after rollback. Reader waits have deadlines; the custom close control remains operable while work controls are locked, and pending shutdown explains what is still running.
- Background result/finished callbacks are guarded at Qt boundaries. Failed save confirmations reset closing/approval state without enabling a window locked independently by account access.
- Active-tab, Split View and detached-window changes refresh the page dimensions shown in the status bar.

## Redaction and native PDF validation

- Actual pixel redaction supports intersecting Separation/DeviceN scan images and Indexed palettes with a supported spot-colour base. Shared images/resources and unaffected pages are preserved; existing transaction, Undo and atomic sanitized save are retained.
- Spot-to-process colour conversion is disclosed before confirmation. This is not a white cover, whole-page rasterisation or a promise of identical spot-ink output.
- Font Preflight / Safe Embed Fonts use the shared native qpdf runtime on Windows and macOS, including independent validation. Unsupported repairs remain blocked; no silent font substitution is introduced.

## PostScript production

- PDF + PostScript requires Ghostscript at Production Review, confirmation and execution, before producing output. Select an existing executable in Settings if the bundled/system runtime is unavailable.
- Zero retained records can still publish approved reconciliation reports without Ghostscript; no empty PDF or PS is generated. PDF-only and offline JDF jobs do not require a PS converter.
- Early failures retain the selected media backend. Template/Overlay summaries distinguish requested output from published PS/JDF and do not mislabel PS failures as JDF.

## Windows and macOS

Windows x64: account-enabled Managed installer and portable.
macOS 13+ Apple Silicon: account-enabled Managed DMG **testing build**, ad-hoc signed and **not Apple notarized**. Intel, Mac OCR and physical printer/inserter acceptance are outside this release.

Both platforms use the same source/version. Existing Windows legacy Managed, Windows account and Mac account signed-update routes remain; project/template/barcode formats and the update public key are unchanged. Splash shows the application version automatically.

## Validation and limits

Release-candidate native regression, packaging, frozen-account startup and Managed handshake checks must pass on this release's frozen SHA. This document is not evidence that a candidate has passed or been published. Results and operator checks are recorded in [the v3.0.7 validation record](RELEASE_VALIDATION_3.0.7.md).

The pre-release integrated product passed Windows core/UI and Linux/macOS core CI, including a synthetic 48-record simplex I25 PDF/PS job with all 48 barcodes decoded. This does not replace candidate-native or operator acceptance.

The original customer's precise redaction exception/native deadlock was not reproduced; confirmed generic lifecycle failures were reproduced and fixed. A permanently stuck native operation cannot safely be killed; pending cleanup remains visible and owned documents are retained. Review production output.

The original bundled qpdf Symantec WS.Reputation.1 report is documented with official source/hash evidence; vendor clearance and Authenticode signing are not claimed. No antivirus settings are weakened.
