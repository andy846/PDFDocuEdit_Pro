# Extract Text Region 2.0 verification

Date: 2026-10-28. Baseline: local main
`a794cbea68cf51972f50864e4f45a6bf303455ed`, initially matching origin/main.
Environment: Windows, `.venv-dev`, PyMuPDF 1.26.6, openpyxl 3.1.5.
All source PDFs used for this work were synthetic. No customer profile was read.

## Measured workloads

Fresh child processes scanned synthetic text PDFs, wrote SQLite, then exported
CSV and write-only XLSX. Twenty text positions were available per source page;
each case selected either 3 or 20 named regions. No images/OCR/complex customer
page layouts were included. Values and final source-page mappings were checked.

| Pages | Fields | Scan seconds | CSV seconds | XLSX seconds | Peak worker working set MiB | Cancel response ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 3 | 0.465 | 0.021 | 0.772 | 73.93 | 1.900 |
| 1,000 | 20 | 2.557 | 0.067 | 2.851 | 75.57 | 2.214 |
| 10,000 | 3 | 4.599 | 0.216 | 5.521 | 80.87 | 5.264 |
| 10,000 | 20 | 26.978 | 0.752 | 28.029 | 81.19 | 4.968 |
| 20,000 | 3 | 10.626 | 0.328 | 9.283 | 88.87 | 9.555 |
| 20,000 | 20 | 60.351 | 1.352 | 55.542 | 89.11 | 8.333 |

Peak working set covers the complete scan/export/cancel child, including Python
and libraries; it is not an isolated algorithm allocation measurement. Cancel
was requested at page 26 through a cooperative progress callback and did not
publish a cancelled database. It does not measure an unusually slow individual
PDF page. Results are individual observations, not a speedup claim against the
legacy tool, and do not predict real customer workloads.

Probe evidence remains local under `build/probes/extract-region-2/`, including
the benchmark helper and JSON results. Initial harness attempts hit restricted
system temp permissions, and an initial fixture-generation run was stopped
during unnecessary PDF deduplication; generation was rerun without that step.
These are not application test passes or application performance measurements.

## Automated coverage and limitations

Targeted tests cover one-region/one-column multiline semantics, Raw/Clean,
selected-page provenance, geometry/no-text/format findings, four rotations with
CropBox, explicit string cells, formula protection, XLSX lossless limits, stale
source/config/selection, no-clobber, atomic cancellation, late commit receipts,
actual isolated Worker preview/scan/export, real Editor snapshot and Workflow
handoff, safe close, preview races, region drawing and cleanup retry.

The full regression result, UI heartbeat and DPI smoke measurements are recorded
after the corresponding final runs. Live account login, actual customer PDFs,
manual Windows GUI UAT, macOS, and a newly packaged build have not been tested
for this feature. Existing release acceptance records do not count as acceptance
of these changes. No installer, update package or release is produced.

## Owner UAT

1. Open a text PDF, including a rotated/CropBox example, and use Extract Text.
2. Draw three named fields, one spanning several lines; compare Raw and Clean.
   Switch Join lines off, then test move/resize and Undo/Redo.
3. Try custom noncontiguous pages, first/random samples, then full extraction.
   Confirm source-page numbers, one column per region and explicit issue rows.
4. Export XLSX/CSV/TXT. Check identifiers with zeros, multiline cells, formulas
   treated as text, and overwrite confirmation. Open a geometry/image-only page
   and confirm that missing text is not silently reported as success.
5. Cancel extraction/export, close the tool during a job, and close the app.
   Reopen a PDF and confirm there are no lingering workers or locked snapshots.
6. Send custom pages to Visual Workflow, close Quick Extraction, and run to
   extraction/review. Check source provenance and independent review/approval.
