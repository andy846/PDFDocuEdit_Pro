# Generic barcode layout — implementation and acceptance

Development update; public application version remains 3.0.2. No release package
or GitHub publication is part of this change.

## Shared contracts

- `composition/engine/generic_layout.py`: declarative segments, explicit total,
  separate data/system/sequence namespaces and stateless formatting.
- Profile v3 adds `layout_mode: fixed`, `total_length` and ordered `segments`.
  Template v12 and Overlay v8 own those profiles; older projects remain readable.
  Legacy v1/v2 profiles retain concatenation behavior until explicitly converted.
- Each segment has a stable ID/name, source, value/reference, length, format and
  overflow policy. Local sequences also have start/step/scope. Unknown lengths
  and Total must be confirmed during conversion; no inferred data truncation.
- Numeric removes existing zero padding before applying the configured width.
  Text requires exact length and retains content. Cycling is permitted only for
  Numeric sequence sources; imported data never cycles or truncates.

## Clients and production

`composition/designer/generic_builder.py` provides the shared retained-draft
editor. Template Designer and PDF Overlay route explicit source contexts to it;
Workflow reuses their saved profiles. Data can be configured before importing;
that is a pending preview, not a successful production check.

`composition/engine/generic_production.py` validates every applicable visible
template barcode before composition, with cancellation and record/page/object/
segment errors. Overlay uses its existing full-page preflight with the same
profile evaluator and module-size validation. Inserted template blank backs
remain blank. Generic marks follow their configured page/visibility scopes.

- `barcode-cycles.csv`: one row per wrapped segment occurrence; complete raw
  sequence, encoded sequence, segment ID/name, object, envelope, sheet, source
  page, output page, record ordinal and source row. Imported/sorted stores retain
  the original source row; generated records use their original ordinal. The
  job log and existing Workflow reconciliation provide source-file identity.
- `barcodes.csv`: exact final-PDF decoding and counts. Template counts include
  both fixed Generic and Inserter marks. Existing legacy Generic template marks
  retain their old behavior. Overlay already audits all barcode marks.
- I25 accepts even ASCII numeric lengths, including 2/4 digits. Its short-code
  decoder uses a per-check native scanner with minimum length 2, without changing
  global decoder state. Full symbol-count and payload comparisons remain required.
- Non-ASCII QR values declare UTF-8 ECI, preventing scanner encoding guesses.
  Payloads stay unchanged; preview and production both use this encoding and
  the object's selected error-correction level.
- Fixed-layout JobId uses the actual production ID; its zero-filled preview
  identity is provisional. Legacy token JobId values remain unchanged.
- Worker preview responses contain only serializable public fields; internal
  typed contexts stay inside the rendering service.

Workflow inspection preserves computed template-sequence identities in its own
temporary result metadata. Its single-record preview restores that namespace;
the saved template and production sequence definitions are unchanged. Inspection
does not publish, approve or invoke production.

## Milestones and focused verification

1. M1: headless model, namespaces and schema migration — commit `6be2221`.
2. M2: shared editor, explicit conversion, source routing and Undo — `521305c`.
3. M3: full-input checks, reports, exact decode, Workflow integration and docs.

Focused checks cover 1,000 generated records with real I25 decoding, rollover
reports, overflow at record 101 before composition, CSV/Excel leading zeros,
data/system name collisions, existing sequences, duplex sheets/odd blank backs,
variable envelopes, hidden invalid marks, cancellation, sorting/source identity,
Workflow inspection/preview and schema save/reopen. UI checks cover retained
invalid drafts, apply/cancel/Undo, explicit conversion, long popups, 960×640,
narrow dialogs, light/dark themes and 200% scaling.

Verification: 215 distinct targeted cases passed across related test batches;
the 200% UI batch also passed all 10 cases. Ruff and whitespace checks passed.
The 1,000-record fixed-layout job reconciled 1,000 generated/rendered/decoded
marks; its two-digit counter produced 900 cycle-report rows, starting at record
101 with raw `100` and encoded `00`. Overflow without cycling failed before any
page was composed or PDF published.

All fixtures are synthetic. Physical inserter acceptance, full regression and
Windows packaging remain in the user's consolidated validation schedule.
