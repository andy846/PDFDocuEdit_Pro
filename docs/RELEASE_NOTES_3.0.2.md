# PDFDocuEdit Pro v3.0.2

Windows x64 — PDF Editing & Print Production Suite.

## What's new

- **Conditional Mail Merge (Workflow v5):** process an ordered list of CSV/TXT/Excel sources through shared preparation, batch sequences and exclusive template routes. Review exceptions and approve individual branches before production. Independent outputs retain original record identity in reconciliation CSV/JSON. This is bounded file iteration and single-level routing; arbitrary cycles and nested loops are not supported.
- **Template Designer:** repeat selected fields across template pages at identical coordinates or equal footer distance; Paste in place and atomic Undo. Document Designer remains the mode name. Small text boxes with clipped field names stay editable without blanking the canvas.
- **PDF measurement:** precise end ticks, smoother dragging, paper rulers, draggable guides, numeric guide positions and guide/page-edge snapping. Alt bypasses snapping; guides and rulers are workspace aids and do not enter the PDF output.
- **Stability:** ruler event callbacks tolerate native widget construction/teardown instead of aborting on missing state. Routed production avoids duplicated batch folders, long automatic filenames and deeply nested native font scratch paths.
- **Duplex media:** repeated Stocks across multi-page templates are supported with physical-sheet consistency checks. Existing PDF+PS/PDF+JDF outputs and printer-profile mappings are retained.
- **Inserter I25 — 18 digits:** shared preset for Template Designer, PDF Overlay and Workflow. Group and sheet sequences default to `00`; group wraps `99 → 00`, sheet numbering restarts per envelope. Six fixed/conditional insert flags, nine-digit customer information, EOG and modulo-10 checksum use one headless service. VS1/VS2 output-bin diversion remains Off.
- **Inserter production QC:** one control per physical sheet front, odd duplex blank backs, placement across template fronts, preflight and final-PDF barcode decoding. CSV reports include full envelope identity, physical sheet, zero-based barcode sheet sequence, output page, inserts, EOG and checksum.

## Quick access

- Document Designer → Create Visual Workflow → **Conditional Mail Merge**.
- Template Designer → Edit / right-click → **Repeat on template pages…**; **Ctrl+Shift+V** pastes in place.
- PDF Workspace → Ruler/Measure; drag from the paper rulers to create guides.
- Barcode properties → Preset → **Inserter I25 — 18 digits** → **Configure…**.
- Template Designer → Page → **Print Media / Stocks…**; Overlay → Production → **Print Media / Stocks…**; Workflow → **Media Assignment**.

## Compatibility and limits

Existing PDF tools and workflow v1–v4 remain supported. New saves use profile v2,
template v11 and overlay v7; older files are migrated on load. Generic barcode
payloads and explicitly saved group starts are retained. Choose `00` in Configure
to change an existing preset's start deliberately.

Example two-sheet payloads with no inserts and zero customer information:
`000000000000000000`, then `000100100000000006` on the final sheet.
More than 99 sheets per envelope or invalid customer digits block generation.
Machine-specific barcode dimensions/read positions and actual printer tray
selection still require operator device tests. Software QC does not establish
physical machine acceptance.

## Downloads and updates

Use **Setup-Windows-x64.exe** for installation or extract **Managed-Portable-Windows-x64.zip**
and run Launcher.exe. Existing managed installations use Help → Check for Updates.
The release also includes a signed Update ZIP, update.json/update.sig and SHA-256
files. No v3.0.2 macOS installer is provided.

Release checks and their practical limits are recorded in
[RELEASE_VALIDATION_3.0.2.md](RELEASE_VALIDATION_3.0.2.md).
