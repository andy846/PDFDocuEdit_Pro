# PDFDocuEdit Pro v3.0 — Document Designer

Planning baseline: v2.5.15. This specification replaces the previous Search/workflow proposal. Existing editor version metadata stays at 2.5.15 until the release process is ready.

## Accepted scope

A distinct Print Composition workspace generates one fixed page per data record from CSV/delimited TXT. First release includes static/variable/mixed text, static images, lines, boxes, Code 128 and QR, PDF backgrounds, field mapping, per-record preview, save/reopen, background production, reconciliation, CSV control reports and JSON job logs. Multiple template pages, conditional rules, splitting, reprint, dynamic pagination and AFP/IPDS are later milestones.

## Architecture

The root composition package contains template, data, engine, production and designer subpackages. Headless models/rendering/jobs do not import Qt or depend on editor sessions. Only the Welcome launch hook and worker entry dispatch integrate into existing app modules. Production and preview run in isolated subprocesses. A disk-backed SQLite import snapshot supports random preview and streamed records. Templates are versioned .pdcx JSON with copied static assets and a data-source reference.

PDF production uses bounded chunks of 500 pages, then the pinned qpdf 12.4.2 runtime assembles one PDF. This bounds composition memory; the assembler's object memory is measured separately. Missing fonts, unsupported glyphs, invalid fields, barcode size violations and text overflow block output. The first release stops on critical errors. Output is published only after page-count verification and reconciliation; failures/cancellation never publish partial PDFs.

## Milestones

M0 architecture/assets/feasibility; M1 template and data models; M2 headless renderer; M3 workspace; M4 import and preview; M5 production jobs; M6 reconciliation and reports; M7 performance and regression. Code 128 and QR are included in the accepted MVP renderer. Each milestone has a local commit and focused tests. Development launch is feature-flagged. Stable release version changes only during a separately reviewed release step.

## Release gates

Template roundtrip/version/schema, CSV/TXT encodings/headers/field collisions, Unicode/Chinese/long values, background fidelity, all elements, barcode decoding, failure/cancellation and reconciliation tests. Full existing suite, Ruff and source verification remain required. Repeatable production benchmarks at 100/1,000/10,000/50,000 records report throughput, peak process memory and output size. 100,000 is an extended benchmark. Synthetic performance results are not guarantees for arbitrary images or background PDFs.

The Windows installed build must contain verified qpdf and font assets, all licence notices, worker dispatch and the barcode packages. Existing tools, installer/update paths and preferences receive regression checks.

## Implementation status — 2026-10-01

The fixed-page MVP is implemented in the isolated feature/print-composition-v3 worktree. See PRINT_COMPOSITION_GUIDE.md for operation and PRINT_COMPOSITION_ACCEPTANCE.md for milestone evidence, measured performance and remaining release limits. This development delivery does not change the public version or declare a v3.0 release date.

Product UI name updated to Document Designer on 2026-10-01. See DOCUMENT_DESIGNER_UX_UPDATE.md for Windows installed font selection and the menu/layers/property improvements; internal engine contracts retain their composition names.

## Post-MVP progress — fixed multiple template pages

The next V3.1 milestone now supports ordered fixed pages per record, page commands/Undo, selected-page preview and exact multi-page reconciliation. Schema 3 reads legacy v1/v2 without changing primary fonts or glyph repairs. See DOCUMENT_DESIGNER_MULTIPAGE.md for operation, evidence and limits. Conditional visibility/basic rules are now implemented in the next development milestone; output splitting remains a later milestone. See DOCUMENT_DESIGNER_RULES.md for schema 4, shared preview/production evaluation, operation and limits.

## UX follow-up — selected-text typography

Selected text objects on the current page now share partial-property editing for exact font
face, point size, alignment, line spacing and colour. Mixed values are identified; unchanged
properties and per-object glyph repairs are retained. Windows face preparation is shared by
the selection and one format change is one Undo command. See DOCUMENT_DESIGNER_BULK_FORMAT.md.
The headless engine, template schema 4 and public version remain unchanged.
