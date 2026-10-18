# Bounded PDF / PostScript production output

## Operator settings

Template Designer Production, PDF Overlay Production results and the Visual
Workflow toolbar share **Output limits & file naming…**. Settings are local
runtime preferences; existing `.pdcx` / `.pdflow` formats are unchanged. A fresh
review is required after changing settings. The controls lock during production.

Defaults for UI jobs: PDF 250 MB, PS 500 MB, at most 1,000 complete envelopes per
part. MB is decimal (1,000,000 bytes). Setting envelope count to Automatic removes
only the count threshold. The 2,000 MB per-file, 20,000 pages per-part and 10,000
parts system bounds always apply. Existing headless jobs without a policy retain
original names and system-only byte limits.

A part never breaks an envelope. Duplex fronts / backs, inserted blank backs,
whole-job sheet numbers, envelope numbers and barcode values retain the existing
planner's semantics. Parts can contain fewer envelopes than requested to fit
actual byte or ticket limits. A single envelope exceeding a bound fails the job.

## Naming and sequence

Default print summary:

`Statement_20261017_part000001_2000SHT_1000ENV_D.pdf`

The matched PS has exactly the same basename and `.ps`. `SHT` is physical sheets,
including sheets with an inserted blank back only once. `ENV` counts complete
mailpieces. `D` means Duplex; `S` means Simplex. Six-digit part indices preserve
lexical print order. Custom structures use the existing declarative variable
engine, including `part.number`, `part.total_number`, `part.sheet_count`,
`part.envelope_count`, `part.page_count`, `part.print_mode_code` and optional
contiguous `part.first_envelope` / `part.last_envelope`, plus `group.value` when
an approved logical group exists. Customer rows cannot silently become a job
name. The part number appears exactly once, cannot be transformed, and precedes
changing part/group fields. The custom structure omits the extension.

The dialog preview is explicitly illustrative. Exact names, counts and byte
sizes are finalized inside staging after size validation, before publication.
The original filename field applies to the Original naming preset. A single
legacy output retains its original flat layout. Multiple parts live in numeric
`part000001` directories. `outputs.csv`, `outputs-manifest.json`, per-part control
reports and source maps identify the complete matched set. Open production PDF
lets the operator choose a part. Do not print both the PDF and PS as separate
jobs; use the format supported by the production controller.

## Implementation and safety

`production/output_policy.py` and `output_naming.py` are headless adapters.
`packages.py` indexes existing render chunks, pages and marks on disk. It selects
bounded whole-envelope candidates directly with the existing qpdf assembler;
there is no unlimited combined PDF before splitting. Oversize PDF, PS or JDF
candidates are subdivided into strictly smaller whole-envelope sets. Rendered
content is reused; resolution, font policy and PS interpretation are unchanged.

Each accepted candidate passes existing PDF validation, the existing applicable
barcode decoder and per-file media / PS checks. Template Direct Content barcode
coverage remains the existing limited scope; the dashboard must not claim all
barcodes decoded when that evidence does not exist. Whole-job reconciliation
and `require_partition_refinement` additionally enforce exact membership and
reviewed logical group boundaries. Policy and naming are signed with the review
job. No authorization requirement or source fingerprint is weakened.

Each part has local file pages plus global output pages. Global sequences are
not regenerated per part. Root barcode audits retain global pages. Parts keep
source maps; artifact checksums are calculated after final naming. The existing
exclusive production claim, journal and atomic directory publication apply to
the entire set. Cancellation, invalid output or a failed part discards the
unpublished print-ready set. `parts-progress.jsonl` records accepted private
candidates as **validated_unpublished**; it is not a resume grant. Cross-restart
resume of in-progress candidates is not offered. Completed packages continue to
use existing checksum-based idempotent recovery.

Review checks a minimum scratch-space floor; each candidate checks a conservative
chunk-based PDF / PS scratch estimate. The estimate is not a converter-size or
OneDrive quota guarantee. Temporary converter / assembler output is sampled, not protected by a filesystem
quota: temporary files may briefly overshoot before the child is terminated and
reaped. Final files must pass exact size checks. Free disk exhaustion remains an
explicit failed attempt; no partial successful set is published. Real printer
RIP capacity is device-specific and may require a smaller user limit.

## Validation

See `build/probes/bounded-output/` for local TDD, isolated regression and synthetic
50,000-envelope evidence. No customer documents are used. The regression suite
includes Template / Overlay barcode QC, Simplex / Duplex, media blank backs,
Workflow logical partitions, authorization, byte refinements, cancellation and
narrow UI. This is development verification, not Windows/macOS installer or
physical RIP acceptance. macOS native testing remains required before release.

Final implementation/test status: [owner review report](BOUNDED_OUTPUT_REVIEW.md).
