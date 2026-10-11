# PDF Production Tools — integration and acceptance

Development work based on v3.0.4; no public version or project format change.

## Operator flow

Open the left Production & Data → PDF Production Tools entry → Analyze in Overview → select Fonts, Flatten or Repair / Normalise → Analyze / Check sources → choose output root → Generate new copy → Results.

Overview is a read-only combined inspection. It does not approve a processing plan. Each operation retains its own drafts and validation. Unsupported checks are displayed, not inferred as OK. Rasterisation is separate from object flattening. Original files and Editor Undo stay intact.

Fonts requires the authorized original face and a trustworthy matching-font reference PDF. Its first repair scope remains static simple TrueType / WinAnsi, with independent qpdf and exact tiled reference checks. CJK/CID and unsupported mappings are diagnostic only. Encrypted/restricted Editor snapshots cannot bypass scan-only restrictions. This does not change Designer glyph fallback.

Batch input is common. Fonts supports batch scan and single-file configuration; font object identifiers are never shared between PDFs. Flatten/Repair retains per-file isolated output and reports. Choose Sources/Refresh is disabled while running. Switching sections, PDF tabs or workspace modes does not restart/cancel the task.

A source revision/form draft/closure makes checks stale. Refresh captures the originating Editor, not whichever PDF is now active. Historical reports remain marked out of date. A late already-published result is retained as outdated evidence rather than losing its output location. Close/exit cancellation retains worker references and temporary directories until the process ends.

## Architecture

- `PdfProductionWorkspace` is a QWidget registered through `DocumentWorkspace.add_tool_tab`; it is not a PDF document session or an embedded dialog.
- `PdfProductionController` owns source context, snapshot lifetime, task coordination, source invalidation and evidence history. Workers use the existing authenticated PDF process transport. Passwords travel through its private stdin channel.
- `PdfOperationControls` and `FontPreflightControls` serve both standalone Dialog hosts and widget Panel hosts. Workflow's settings-only dialog remains compatible. The existing PDF services, font validators and atomic publication are unchanged.
- `analyze_overview` composes the existing PDF/font inspections sequentially, isolates failures by file, and checks both inspectors used the same source hash. It does not create a new PDF engine or fuse their scans.
- The existing tool-tab router now handles all registered tool tabs for menu/shortcut binding and shutdown. PDF navigation stays available; Save/Undo is disabled for this tool. Legacy command IDs route to the matching section.

## State and reports

Analysis/production/failure results keep section, source identity, generation, settings and outdated status. JSON exports full evidence; CSV exports font resources through the existing font exporter or per-file operation summaries with spreadsheet formula protection. UI summaries remain human readable. Publication still uses the existing validated job bundle; a failed task cannot be displayed as successful.

Settings/approvals/source fingerprints are separate from the PDF Editor's document state. Section changes are not operations and do not clear drafts. No automatic restoration after restart, automatic processing, chained transformations, font substitution or extra engine is introduced.

## Targeted acceptance

Tests cover actual Overview and Flatten output, source preservation, pending settings, source change with late results, stale-history marking, shared source lists, font drilldown and security, task cancellation / cleanup, repeated entry focusing, unsaved snapshots, menu/shortcut isolation, existing Merge/mode routing, CSV/JSON evidence, source hash mismatch and bounded input.

Dark/light and large-font narrow UI snapshots are generated under `build/pdf-production-ui` (ignored). CI includes the new headless/GUI tests. Full release regression and Windows/macOS native packaging remain separate release gates. Offscreen screenshots are layout evidence, not native Mac or printer acceptance.

Existing sidebar tests intentionally change from three buttons to one searchable combined entry; old command routes remain covered rather than removing their tests.
