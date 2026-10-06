# Inserter I25 — 18 digits: implementation and focused acceptance

Date: 2026-10-07. Development change; public version remains unchanged.

## Milestones

- M1 (`8295b12`): shared declarative profile, checksum, insert rules and versioned migration.
- M2 (`6b4a75e`): physical-sheet composition, streamed preflight and final-PDF decoding audit.
- M3: shared preset editor, same-position template placement, readable dropdowns, Workflow estimates, documentation and focused UI checks.

The shared engine has no Qt dependency. Template Designer and PDF Overlay configure the same profile; Visual Workflow uses their saved projects and generation services.

## Payload contract

`Group(2) + Sheet(2) + Inserts1–3(1) + Inserts4–6(1) + EOG(1) + Location(1) + Customer(9) + Check(1)`.

Group start defaults to 00 and wraps through 99, 00, 01. Full envelope identity is retained in the audit. Barcode sheet sequence starts at 00 per envelope and follows the actual physical-sheet plan, including media-induced blank backs. EOG is 1 only on the final sheet. VS1/VS2 diversion is off; Location is zero. Customer information is exactly nine ASCII digits, or nine fixed zeros. No truncation, implicit padding or extra checksum is performed.

Checksum is `(-sum(digit * alternating 3,1 weights from the left)) % 10`.
Current examples use the corrected 00 group and sheet starts; the checksum formula remains unchanged:

- First envelope, first of two sheets: `000000000000000000`.
- First envelope, second/final sheet: `000100100000000006`.
- A zero weighted remainder gives check digit `0`.

## Use

Select a barcode → **Barcode properties → Preset → Inserter I25 — 18 digits → Configure…**.
Configure Sequence, Inserts, Customer info and Placement; inspect the segmented payload and barcode in Preview.

Printing is selectable without Media; active Media settings remain authoritative. The template placement operation lists required front-page targets, checks geometry/conflicts and commits all copies/updates as one Undo. PDF Overlay automatically sets I25, front-only scope, machine control and required front read positions. Generic profiles preserve their existing token behavior.

## Output and migration

Preflight rejects missing/duplicate visible front controls, invalid customer/conditional fields, more than 99 sheets, unsuitable dimensions or out-of-page placement. Errors identify record/envelope, page, object and affected field where applicable. Production audits the decoded final payloads and writes `barcodes.csv` with envelope, sheet, output page, insert masks, EOG, check digit and QC status. Generation and decode counts must reconcile before publication.

Profile/template/overlay formats save as versions **2/11/7**, while retaining legacy readers. Tests that assert the current migrated version were updated; old-format input fixtures remain. No public application version or dependency changed.

## Verification

- **228 focused tests passed**: profile encoding/migration, I25 rendering, Template Designer/Overlay controls, generic compatibility, handoff, sequences, rules, Excel-source migration, media planning and production.
- Included a real **1,000-envelope PDF generation and decode** test, group rollover/full identity, four-page duplex, odd and variable envelopes, media-induced blanks and Workflow generation without Media.
- UI checks cover narrow dialogs, fixed footer, long combo popups, drafts, cancel and one-step Undo; light/dark screenshots were inspected using offscreen Qt with registered Windows fonts.
- **Seven UI tests passed at 200% scaling**. Offscreen screenshots include a 960 × 640 physical-pixel dialog at that scale.
- Changed Python files passed Ruff; `git diff --check` passed.

Machine-specific dimensions, orientation and reading position remain **validation pending**. Software decode does not constitute a physical inserter test. Full regression, packaging and release remain part of the user's later combined acceptance.

## Zero-start correction

Both new preset sequences start at 00. Sheet context remains one-based for physical planning and EOG; only encoded sheet digits use `physical sheet - 1`. The CSV adds **Sheet sequence** alongside the physical **Sheet** number. Explicit saved group starts remain configurable; existing projects can select Group start 00 in Configure. Generic profiles retain their payload logic.

Correction verification: **37 profile, production and UI tests passed**, including the 1,000-envelope generation/decode case. Ruff and diff checks passed; the wider milestone suite above was not rerun for this targeted correction.
