# Optional barcodes in PDF envelope overlays

Date: 2026-10-02 (Hong Kong)

## Fixed

A text-only/running-sequence overlay previously failed with:
`Required barcode read position needs exactly one visible control barcode; found 0.`

The required-position check was unconditional. Final reconciliation also counted only envelopes encountered in barcode QC, so simply skipping the first check still left zero-barcode jobs unverified.

- Machine read-position validation is now enabled when at least one project object is explicitly marked **Machine control barcode**. With no such object, text-only overlays, page copies and ordinary non-control barcodes are supported.
- Declared control barcodes still require exactly one visible control barcode at each required read position. Missing/hidden or duplicate controls continue to fail.
- Final PDF validation, source/page reconciliation and QC for every actual barcode remain mandatory. Once output validation and all marks' decoding finish, envelopes without marks are counted as successful too.
- New source inspection creates the running-sequence text object without automatically inserting a Code 128 barcode. Users add barcode objects explicitly. Adding the first barcode marks it as machine control, as before; unchecking that option makes it an ordinary barcode while retaining its decoding QC.
- Required read positions is disabled with a Not required tooltip when no control object exists. Text objects cannot enable Machine control barcode. Undo restores the requirement when it restores a control object.
- `job.json` and `control.csv` expose `control_barcode_required`; JSON records a null required scope when the requirement is inactive.

No project schema/version change or new dependency. Existing text-only projects need no migration. Existing projects containing control objects retain their machine checks.

## Focused validation

**8 passed in 2.79 s**, changed-file Ruff and `git diff --check` pass:

- Synthetic 16-page / 8-envelope jobs: no overlay objects, running-sequence text only, and ordinary non-control Code 128.
- Source hashes remain unchanged; output page/text, reports and barcode counts checked. No-barcode jobs do not invoke barcode decoding.
- Duplicate controls fail; existing missing-control/page-boundary and QC/reconciliation failure cases still refuse publication.
- UI source inspection creates no implicit barcode; checkbox/deletion/Undo updates required-position controls.

No full regression, performance benchmark or packaging run.

The open source application's generation uses a fresh worker process, so the engine fix is available on the next Generate without discarding the open project. Restart after saving is needed to load the UI/default-object changes into the already running main window.
