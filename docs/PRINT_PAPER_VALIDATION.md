# Printing paper validation and effective geometry

Single and Batch Print share one GUI-owned paper policy. PDF Page Size requests
paper matching the first selected page (batch: first page per file); it is not an
instruction to automatically shrink to A4. Printer settings preserves the
configured paper and margins; the application orientation choice still applies.
Explicit native-dialog orientation overrides are retained across the batch. Capabilities and limits come from the driver, never tray-stock
inspection. PDF output is a separate backend and permits arbitrary valid sizes.

Unsupported, uncertain, rejected or inconsistent layouts require an operator
choice before spooling. The previous driver layout is captured before requesting
custom paper. Operators can choose it, a reported standard size, cancel, or skip
a batch file. Identical-case consent is scoped to this operation and invalidated
by printer/preferences changes; it is not saved in profiles.

The existing renderer now offers an opt-in retained raw frame. The GUI begins the
Painter only after that frame is ready, reads live viewport/DPI/origin, and asks
for confirmation if the driver changed the area. A worker then scales the same
frame; no second PDF raster or GUI-thread image scaling is required. Each new page
is measured after newPage. Normal printer coordinates start at the printable
origin; pageRect margins must not be added again. Actual/Custom scale and shifts
remain intentional and can exceed the printable area. Cancellation after a native
job starts cannot guarantee a queued sheet is retracted.

Legacy tuple-returning render_print_page callers and synchronous painting remain
supported. Paper geometry diagnostics use numeric dimensions/capability flags;
no PDF field values, credentials, driver private blobs or document contents are
logged. No project format, update architecture, dependency or public version changes.

## Validation

Use tests/test_print_paper.py and tests/test_print_geometry.py with the existing
printing, process, preferences and relevant tools-port tests. Fixtures generate
synthetic PDFs. Test unsupported/unknown/custom sizes, rejected setters, consent,
late A4 fallback, cancel/skip, Actual/Custom scale, asymmetric margins and UI layout.
A simulated late driver change is not a real Windows-driver compatibility result.

Before physical acceptance: print the same 450 × 500 mm four-corner test page with
PDF Page Size and explicit A4 in Single and Batch Print, recording driver/version,
configured/requested paper, capabilities, DPI, layout/device/viewport geometry and
actual tray stock. A driver/DFE that silently substitutes stock without reporting
it cannot be detected reliably by this application.

## Targeted verification — 2026-10-15

- 60 printing/paper/geometry/preferences/related UI cases passed (63 unrelated
  cases deselected); 21 CI/source-contract checks passed. Targeted Ruff and
  git diff whitespace checks passed. This is not a full application regression.
- In-memory PDF QPrinter fixtures confirmed late A4 placement without a second
  raster, no drawing after rejection, printable-origin handling, retained
  Actual/Custom scale, cancellation, batch skip and native orientation retention.
- Isolated offscreen screenshots and focus/reveal checks covered paper confirmation,
  Single Print and Batch Print in light/dark at 100%/200%, bounded to a 960 × 640
  physical area. Scrollable settings and separate action footers remain reachable.
  This does not prove native driver dialogs or hardware behavior.
- Fresh whole-branch review found a batch native-orientation override regression;
  its test failed before repair and passed afterward. Operator skips are shown as
  Skipped rather than Error; actual failures retain Error and their diagnostic log.
- No physical jobs, packaging, update artifacts or releases were produced.
