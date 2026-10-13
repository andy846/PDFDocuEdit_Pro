# PDF production cleanup and variables — development implementation

Baseline: v3.0.2. Public version, template/overlay/barcode schemas unchanged.
This document describes development code; it is not a release announcement.

## Service boundaries and reuse

| Area | Implementation / reused components |
| --- | --- |
| Variable grammar and formatting | `core/variables/{model,parser,resolver,transforms,paths}.py`; headless, bounded, whitelist only. Legacy template `parse_value` / `resolve_value` delegate to the same parser/resolver while retaining saved grammar. |
| Job naming | `ProductionJob.variable_context`, `OverlayJob.variable_context`, `BatchJob.variable_context`; captured clock/identity, strict resolution and Windows-safe filename planning. `ui/variable_name.py` provides example/prepared previews. |
| PDF plans and diagnosis | `core/pdf_operations/model.py`, `analysis.py`; MuPDF syntax/open diagnosis, selected-page appearance inventory, qpdf syntax checks. Coverage that cannot be reliably checked is explicitly Not checked. |
| Flatten | `appearances.py::flatten_page`; promote existing Normal Appearance with native PDF coordinates/resources. Original page tree retained. `core/annotation_io.py` uses the same implementation. |
| Generate and validate | `service.py::execute`; existing PyMuPDF, safe metadata helpers, `validate_pdf_file`, `atomic_output`, `PlatformService.run_cancellable`, Production Preflight (`core.analysis.inspect_and_analyze`). qpdf path/hash verification extracted to `core/pdf_runtime.py`. |
| GUI / processes | `dialogs/pdf_operations.py`, established `composition.designer.process.Worker`; dedicated `--pdf-operations-worker` dispatch before Qt imports. Passwords use private stdin, not request JSON/CLI/logs. |
| PDF Workspace | `core/viewer.py` creates an owned current-revision snapshot and opens the dialog. Original editing state and Undo history remain untouched. Pending form drafts must be applied/discarded before snapshot. Exit cancels and waits for workers after unsaved confirmations. |
| Batch | `core/pdf_operations/batch.py`; serial service calls, per-file isolation/audit, shared variable path checks. No second renderer/batch worker engine. |
| Workflow | `workflow/pdf_operations.py` adapts the same service. Registry, node settings, inspection and execution share options. Intermediates stay in scratch; only the existing reviewed Output stage publishes production. |

## Output and failure policy

Analysis approval is tied to source SHA256, options and page count. Generate
privately → readable/page-count/geometry checks → page-by-page visual/searchable
text QC where applicable → optional Preflight → atomic job-directory publication.
Source hashes are rechecked before publication. A failed/cancelled operation
retains JSON evidence when the output root is writable, with zero published PDFs.
Batch cancellation preserves earlier completed bundles; a batch is not a single
atomic transaction. PDF/CSV/JSON share a new bundle, never silently overwrite input.

Work snapshots, qpdf candidates and Preflight inputs live in a separate owned
temporary directory; user-selected PDF basenames cannot collide with those
internal files. Confirmation-only flags preserve the analyzed inventory. Changing
the source password or processing options invalidates it. Batch analysis exposes
required signature/recovery confirmations, validates ranges per source and shows
per-status completion counts. See the 2026-10-07 consolidation record for targeted
verification performed on 2026-10-08.

Safe Repair rewrites with qpdf and saves through the current PDF stack. Normalise
only performs explicit removal/flatten/crop choices. Rasterisation is separate,
per page, with pixel limits, and never automatically adds OCR. Missing Normal
Appearances, unapplied redactions and XFA are not guessed. Hidden/Invisible/NoView
objects remain interactive and are reported as retained; only visible appearances
are flattened. Non-raster transparency
flattening and complete action/security inventory are not implemented. Font
embedding is not repaired automatically. Unknown/unrepairable structures fail.

Signed sources need explicit acknowledgement; a derived file does not retain
cryptographic validity. Signature widgets are identified, not cryptographically
verified. An image of handwriting is not a digital signature. Encrypted input
needs encrypted output. qpdf encrypted-output checks are marked Not checked;
authenticated MuPDF readable/QC checks still run. MuPDF's encrypted state is
captured before authentication to avoid a reproduced 1.26.6 re-query failure.

If MuPDF cannot render the original but qpdf recovers it, explicit limited-QC
approval is required. Output is Needs review, compared only to recovered baseline.
Workflow refuses to treat such an intermediate as production-ready.

## Variables and compatibility

Supported namespaces: system/input/job/batch/workflow/record/envelope/sheet/
production. Fields must be supplied by that integration: unavailable values fail
strictly. Formatting: upper/lower/trim/title/capitalize/replace/pad/truncate/default/
date. Pad never silently truncates an overflowing number. No eval, arbitrary
expressions, Python, shell expansion or filesystem traversal by resolved values.

Naming sanitises Windows characters/reserved devices, applies bounded UTF-16
lengths and checks actual duplicate paths. Original customer values are retained.
Mail Merge retains its distinct-PDF-basename delivery rule across the queue. Batch time and
sequence are frozen before checks; retries retain the naming context and isolate
new attempts. Example previews are labelled; they do not promise a future job ID.

Designer text uses the common service but retains `{{Field_Name}}` grammar in the
current saved schema. Expanded text/barcode/folder/report-column variables remain
later integrations. Existing `{{WorkflowSeq}}` resolves to its original imported/
generated field first. Namespace aliases do not override an existing field.

New PDF workflows use v6 because older readers cannot understand cleanup nodes.
Only PDF workflows use v6; existing v5 conditional Mail Merge remains unchanged.
Old saved workflows upgrade by Save As. v1–v5 load; older installations cannot
open v6. Batch run records include naming contexts; these are development-state
records, not a downgrade-compatible cache format. Existing project sources load
without those contexts and acquire them when checked. No template version bump.

## Test and performance gates

Targeted tests cover parser/formatting/legacy aliases, paths, namespaced CJK values,
appearance flattening and partial pages, page rotation/CropBox, form appearances,
encrypted reads/re-encryption, original bytes unchanged, cancel, source changes,
failure audits, batch partial failures, per-node caches, inspection provenance,
draft settings, responsive dialogs and existing composition/overlay/workflow gates.
Generated fixtures are deterministic; actual production PDF variety still needs
operator validation. Visual comparison uses current MuPDF at 72 dpi, not an
independent Acrobat certification. High-resolution appearance fixtures additionally
compare pixel differences. Full regression/Windows packaging remain the agreed
combined release gate.

Repeatable benchmark:

```powershell
.venv-312/Scripts/python.exe scripts/benchmark_pdf_operations.py --pages 100 1000
.venv-312/Scripts/python.exe scripts/benchmark_pdf_operations.py --operation repair --pages 100 1000
```

Benchmarks run isolated processes and record time/pages-per-second/process peak
memory/output bytes. Simple local synthetic pages do not guarantee network,
image-heavy or malformed-customer performance. Raster buffers are released per
page; full-document MuPDF object tables and rewriting still grow with PDF size.
Large jobs show progress, use bounded raster buffers and offer safe cancellation;
constant memory for arbitrary PDF documents is not claimed.

### Development validation on 2026-10-07

Focused PDF/appearance/normalise/UI/workflow and existing annotation/transaction/
atomic-output suite: **106 passed**. Focused variables/inspection/Mail Merge/UI/
workflow suite: **69 passed**. These overlap and must not be added as a unique
test count. Earlier wider affected-suite run found two failures (inspection name
context and the established duplicate-basename rule); both were fixed and
verified in the latter focused run. New cleanup settings/save/load/Undo tests
add an explicit v6 GUI/serialization check. Ruff and diff whitespace checks pass.

Rendered new dialog at logical 960×640 in dark/100% and light/200% modes. Footer
keeps Analyse/Generate/Close visible; secondary result actions belong to content.
This is programmatic Qt render verification, not a printer or installer check.

| Synthetic case | Total seconds | Pages/sec | Peak process MiB | Output bytes |
| --- | ---: | ---: | ---: | ---: |
| Flatten, 100 pages | 0.91 | 109.9 | 76.4 | 103,497 |
| Flatten, 1,000 pages | 8.84 | 113.2 | 85.0 | 1,043,429 |
| Safe Repair, 100 pages | 1.06 | 94.5 | 76.8 | 97,512 |
| Safe Repair, 1,000 pages | 9.48 | 105.4 | 85.6 | 984,601 |

Single-run samples on the current Windows machine, including analysis/generation/
validation; no cold/warm median claim. Process peak excludes external qpdf peak.
Detailed local reports are under ignored `.benchmarks/pdf-operations/`.
