# Inserter I25 — 18 digits: implementation and focused acceptance

Date: 2026-10-07. Development change; public version remains unchanged.

## Milestones

- M1 (`8295b12`): shared declarative profile, checksum, insert rules and versioned migration.
- M2 (`6b4a75e`): physical-sheet composition, streamed preflight and final-PDF decoding audit.
- M3: shared preset editor, same-position template placement, readable dropdowns, Workflow estimates, documentation and focused UI checks.

The shared engine has no Qt dependency. Template Designer and PDF Overlay configure the same profile; Visual Workflow uses their saved projects and generation services.

## Payload contract

`Group(2) + Sheet(2) + Inserts1–3(1) + Inserts4–6(1) + EOG(1) + Location(1) + Customer(9) + Check(1)`.

Group is the envelope sequence: first envelope 00, then 01, wrapping 99 → 00; all sheets within an envelope have the same group. Sheet sequence counts physical sheets across the entire production job, starts at 00, wraps 99 → 00, and never resets at envelope boundaries. Duplex front and back share one value; inserted blank backs do not increment the counter. Each separate production job starts again at 00. Full envelope identity, within-envelope sheet number and full job sheet number remain in the audit. EOG is 1 only on the final sheet of each envelope. VS1/VS2 diversion is off; Location is zero. Customer information is exactly nine ASCII digits, or nine fixed zeros. No truncation, implicit padding or extra checksum is performed.

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

Current profile/template/overlay formats save as versions **3/12/8**, while retaining legacy readers. I25 v3 records `sheet_sequence_scope: job`; old profiles without this attribute retain their former encoding during read/preview. Production requires explicit conversion: Update I25 sequences resets Group start to 00, uses continuous job sheets, preserves inserts/customer/geometry and resets device verification to pending. Designer commits conversion as one Undo; headless and Workflow checks block legacy I25 with instructions to update in Designer. Generic profiles keep their previous semantics. Tests that assert the current migrated version were updated; old-format input fixtures remain. No public application version or dependency changed.

## Verification

- **228 focused tests passed**: profile encoding/migration, I25 rendering, Template Designer/Overlay controls, generic compatibility, handoff, sequences, rules, Excel-source migration, media planning and production.
- Included a real **1,000-envelope PDF generation and decode** test, group rollover/full identity, four-page duplex, odd and variable envelopes, media-induced blanks and Workflow generation without Media.
- UI checks cover narrow dialogs, fixed footer, long combo popups, drafts, cancel and one-step Undo; light/dark screenshots were inspected using offscreen Qt with registered Windows fonts.
- **Seven UI tests passed at 200% scaling**. Offscreen screenshots include a 960 × 640 physical-pixel dialog at that scale.
- Changed Python files passed Ruff; `git diff --check` passed.

Machine-specific dimensions, orientation and reading position remain **validation pending**. Software decode does not constitute a physical inserter test. Full regression, packaging and release remain part of the user's later combined acceptance.

## Continuous-job sheet correction

The production planner provides one-based `JobSheetNo` separately from envelope-local `SheetNo`/`SheetCount`. I25 encodes `(JobSheetNo - 1) % 100`; EOG uses local `SheetNo == SheetCount`. Template profile context offsets by actual output-page count, including padding and media-induced blank backs. Overlay uses the same final page plan. `barcodes.csv` adds **Job sheet** without changing the existing **Sheet** column.

Production exposes Simplex/Duplex and expected page/sheet/control counts. I25 Generate opens a review dialog with the same printing selector; changing the draft and cancelling leaves printing unchanged. Active Media remains authoritative. Apply barcode to required fronts lists targets, checks geometry/duplicate conflicts and asks before replacing existing single front controls. The Production page can scroll on short windows and result actions stack on narrow windows.

Targeted verification includes imported 200-record single-page data, 1,000 real decoded envelopes, variable envelopes, two-page first-only controls in both print modes, four-page duplex, media-inserted blank backs, legacy conversion/Cancel/Undo and Workflow production. Full regression, packaging, release and actual inserter proof remain separately scheduled.

Current correction verification: **141 distinct targeted tests passed across focused runs**, including 200 imported records and 1,000 generated envelopes with final-PDF decoding. All **15 I25 UI tests passed at 200% scaling**, with light/dark coverage. Changed Python files passed Ruff and the working diff passed whitespace checks. These are synthetic/offscreen checks; no full application regression, packaging or physical inserter proof was performed in this round.
