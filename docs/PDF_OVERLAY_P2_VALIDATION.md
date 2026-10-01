# PDF envelope overlay — P2 headless validation

Date: 2026-10-02. Development milestone, not a production release or inserter certification.

## Delivered

- Immutable source snapshot with SHA-256 validation; fixed-page grouping and lazy source/output/sheet mapping.
- Sequence, Code 128 and QR marks; declarative payload tokens and independent element/read-position scopes.
- Simplex and duplex grouping. Odd duplex groups receive an explicit blank back.
- Separate vector layer added to copied source pages. Original embedded font programs, text and annotations are preserved; copied source fonts are never subset.
- Bounded layer batches are completed before grafting. Growing a source layer document after the first graft caused MuPDF object-range errors, so the implementation freezes each batch first.
- CropBox placement uses an temporarily unrotated target and restores its original rotation. Verified at 0/90/180/270 degrees.
- Final assembled PDF is reopened and each barcode crop is decoded against its exact expected payload. Missing, duplicate, hidden or incorrectly decoded control marks prevent publication.
- CSV envelope/page/barcode/control reports, exact-payload JSONL audit and machine-readable job log.
- Cancellation, source changes, missing glyphs, invalid scope coverage and failed reconciliation cannot publish a partial PDF. Diagnostic reports distinguish composed envelopes from envelopes verified by final QC.
- Existing background worker has separate overlay tasks. Engine depends on no editor or Qt widgets.

## Synthetic local benchmark

Command: `python scripts/benchmark_pdf_overlay.py --pages 300 3000`; repeat with `--duplex`.

Single-run samples on this Windows development machine, including final barcode QC:

| Mode | Source pages | Envelopes | Output pages | Sheets | Blank backs | Decoded marks | Generation + QC | Composer peak | Assembler peak |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Simplex | 300 | 100 | 300 | 300 | 0 | 300 | 2.35 s | 83.5 MiB | 17.9 MiB |
| Simplex | 3,000 | 1,000 | 3,000 | 3,000 | 0 | 3,000 | 17.69 s | 97.6 MiB | 98.9 MiB |
| Duplex | 300 | 100 | 400 | 200 | 100 | 300 | 2.69 s | 83.4 MiB | 18.4 MiB |
| Duplex | 3,000 | 1,000 | 4,000 | 2,000 | 1,000 | 3,000 | 23.10 s | 98.9 MiB | 103.9 MiB |

Fixture contains simple original text and overlay sequence/Code128; it is not an image-heavy customer PDF or network-source benchmark. These are samples, not medians or throughput guarantees. Composer page batches are bounded; source metadata and the final qpdf assembler still consume memory according to PDF complexity/page count. No constant-total-memory claim is made.

Raw benchmark reports remain in the ignored `.benchmarks/pdf-overlay` directory. No customer PDF/data was used.

## Gates still pending

P3 GUI integration and Windows acceptance are recorded separately. Actual machine protocol, reader position, print scaling and physical inserter sampling need the machine model and a working payload sample. Default profile status remains `pending`; software decoding does not imply machine compatibility.
