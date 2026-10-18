# PostScript output: investigation and lossless performance repair

## Scope and baseline

Investigated on Windows x64 against product worktree `print-composition-v3`,
branch `codex/deep-search-restore-layout`, HEAD
`a5cd66db8d071c6db733c1f10e4f926751b83a76` (v3.0.9 plus validation documentation).
The pre-existing M0/M4 uncommitted changes are preserved. No version, format,
dependency, production authorization, PDF-generation algorithm or printer rules change.

The owner supplied a six-page template for investigation. Only the template was
loaded; its linked customer dataset was not opened. Benchmarks use synthetic values
and the existing renderer, sequence engine, chunk assembler and media plan.
Local probe inputs/results remain under `build/probes/ps-output-performance/`.
They are not release assets or customer production output.

## Confirmed causes

1. **Duplicate PDF resources across repeated records/chunks.**
   `composition/engine/renderer.py:Renderer.render` imports page backgrounds and
   renders variable elements. `composition/production/generator.py` saves chunks
   with `garbage=1`; `_assemble` joins them using the existing qpdf service.
   `composition/media/postscript.py:export_postscript` previously sent this PDF
   directly to Ghostscript. Repeated objects/streams cause expensive repeated
   converter work. The controlled 180-page input had 1,586 xref entries; lossless
   deduplication reduced this to 392 with unchanged rendered page samples.
2. **Cancellation-file I/O on every PS line.**
   `postscript.py:program_dsc` called `check_cancel` for every bounded readline.
   `composition/worker.py:dispatch` provides a cancellation callback backed by
   `Path.exists()`. Large ASCII PS files therefore incurred millions of filesystem
   queries during an otherwise streaming media-programming pass.

The original running job was CPU-active and advancing, not proven deadlocked.
Its elapsed time alone did not establish the cause. The supplied template had no
identified transparency groups, soft masks or non-normal blends. Transparency was
therefore not established as this template's bottleneck. Changing font subsetting
or increasing Ghostscript memory buffers did not improve the controlled workload;
those settings are unchanged.

## Implemented repair

- `_prepare_converter_input` saves a **private temporary PDF** with the existing
  PyMuPDF `garbage=4, deflate=True`, merging duplicate objects/streams without
  requesting resampling, rasterisation or font replacement. It verifies page count,
  MediaBox, CropBox and rotation before starting Ghostscript. It never saves the
  original production PDF. Preparation failure/cancellation propagates through the
  existing unpublished staging and cleanup path.
- `program_dsc` polls cancellation at roughly 50 ms intervals within PS data,
  retaining immediate entry, page-header and completion checks. This bounds repeated
  cancellation-file reads while retaining cooperative cancellation. Blocking I/O
  can exceed that interval; it is not a hard real-time deadline.
- The existing progress channel identifies **PostScript preparation**. The existing
  report additionally records preparation seconds and input/prepared PDF byte counts.
- Resolution (including 600 dpi), EmbedAllFonts, SubsetFonts, DSC checks, fronts/back
  media requests and the full Ghostscript PS interpretation remain unchanged.
  Page count/dimension reconciliation and outer atomic publication still apply.
- No global cancellation framework, new worker, alternate converter, reduced-quality
  mode or parallel PS concatenation is introduced.

PyMuPDF's native save cannot be interrupted mid-call. Cancellation is checked before
and immediately after, including after the progress callback, and during geometry
verification. Preparation took about 7.25 seconds in the 2,388-page probe. Very large
or resource-heavy inputs may take longer and require an additional temporary PDF.

## Measurements

These are local measured workloads, not a guarantee for every customer PDF.
The baseline and optimized 180-page tests used the same synthetic document,
Ghostscript build and 600 dpi options.

| Controlled 180-page phase | Before | Optimized |
|---|---:|---:|
| PDF to PS conversion | 37.227 s | 5.669 s |
| Media programming, original PS bytes | 80.344 s (per-line file check) | 2.762 s (50 ms file check) |
| Full interpretation of the respective PS | 26.388 s | 17.718 s |

The media experiment isolates polling with the **same original PS input**. Its
programmed PS and audit CSV hashes are byte-identical for no callback, per-line
callback and bounded callback. This is separate from comparing PS containers
produced from different PDF resource representations.

A subsequent **actual patched `export_postscript`** run on the 180-page document,
while other work was active, took 41.331 seconds in total: preparation 0.203 s,
conversion 8.328 s, full validation 32.453 s. Source SHA256 stayed unchanged,
preparation progress was visible and no private converter directory remained.
These timings are not combined with earlier phases into a fictitious end-to-end A/B.

### Large synthetic workload

398 synthetic records, six template pages each, 2,388 output pages, 600 dpi;
existing chunk sizes 504/504/504/504/372:

| Phase | Seconds |
|---|---:|
| Compose and assemble | 17.868 |
| Private lossless preparation | 7.246 |
| PDF to PS | 79.106 |
| Media programming | 3.559 |
| Full PS interpretation | 272.145 |

Approximately 6 min 20 s across these measured phases. This probe used the approved
optimization and polling strategy before the final service integration; the actual
service was independently exercised above and by production/overlay/split tests.
The original customer job and this synthetic workload are not an exact full-job A/B.
The full large baseline was not rerun merely to reproduce a long delay.

PDF input size fell from 5,776,786 to 1,210,151 bytes; programmed PS was 49,682,012
bytes. Measured process peaks were approximately 118 MB for the preparation/renderer
Python process, 65 MB for ps2write and 496 MB for pdfwrite. These are observations,
not memory limits or promises for larger PDFs.

## Quality evidence

- Source versus deduplicated 180-page PDF: **all 180 pages byte-identical as 150 dpi
  rendered pixels**; pages 1, 2, 6, 60, 120 and 180 also identical at 600 dpi.
- Baseline and optimized PS, each fully interpreted back to PDF: those six sampled
  pages have **byte-identical 600 dpi rendered pixels**.
- Large input versus deduplicated PDF: 600 dpi pixel equality at nine pages,
  including chunk boundaries and the last page.
- All 2,388 interpreted pages retain count and dimensions within the existing
  production tolerance (maximum measured rounding 0.004456 pt; tolerance remains
  0.5 pt). The first probe incorrectly required exact floating-point equality;
  this probe assertion was corrected, without changing product validation.
- 24 sampled barcodes across six synthetic records decoded with exact payloads
  using the existing decoder. This is **sample coverage**, not a claim that every
  barcode in the large PS was decoded or that Direct Content QR has new coverage.
- Automated tests independently exercise crop/rotation/searchable text/pixels,
  actual converter input, unchanged source, full validation, polling, cancellation,
  disk-full and invalid prepared-geometry cleanup.

Existing PS conversion may already change PDF text extraction metadata and flatten
unsupported PDF appearances at the configured resolution. The repair does not widen
those capabilities or claim universal visual equivalence for every PDF. Actual device
paper selection and print quality still require native printer proofing.

## Verification and limitations

Final targeted results: **255 passed, 0 failed, 0 skipped** across three runs:

| Gate | Result |
|---|---|
| PS/performance/progress, Media, Duplex, production, I25/Generic, authorization, output safety and recovery (11 modules) | 182 passed / 228.66 s |
| PS UI/activity/review and Workflow media/review (5 modules) | 52 passed / 77.02 s |
| Source contract and CI selection (2 modules) | 21 passed / 6.96 s |
| Ruff on changed Python files; `git diff --check` | Passed |
| Existing CI focused selection includes the new performance test module | Passed |
| Fresh read-only code review | No Critical/Important findings |

Test-first evidence: four initial performance/safety assertions failed against the
old implementation (one existing final-cancel assertion passed); the initial green
set passed six tests. Additional fault tests then exposed missing cancellation
immediately after the preparation progress callback (nine passed, one failed);
after adding that boundary check all ten new cases passed.

The first broad run used an overly deep explicit `--basetemp` beneath the probe
folder: 171 passed / 11 failed, and the UI group 48 passed / 4 failed. Workflow
preparation could not open nested SQLite paths before PS conversion was reached.
An isolated split case reproduced the failure and passed with the shorter
`build/probes/psq-split` path. Complete short-path reruns (`psr2`, `psu2`, `psc2`)
produced the passing results above, without product path/database/auth changes.
Initial failing test IDs (all passed on the corrected-path reruns):

- `tests/composition/test_postscript.py::test_split_ps_is_rebased_and_has_one_output_per_package`
- `tests/composition/test_postscript.py::test_ps_zero_retained_records_publish_reports_without_ghostscript`
- `tests/composition/test_media.py::test_template_media_without_workflow_node_and_split_packages`
- `tests/composition/test_media.py::test_split_ticket_size_limit_is_per_output_not_global`
- `tests/composition/test_generic_production.py::test_workflow_inspection_materialized_sequence_and_preview`
- `tests/composition/test_generic_production.py::test_workflow_data_segment_issue_keeps_field_identity`
- `tests/test_production_recovery.py::test_branch_unexpected_failure_persisted_and_approvals_revoked`
- `tests/test_production_recovery.py::test_later_branch_failure_preserves_committed_first_job`
- `tests/test_production_recovery.py::test_branch_report_failure_retains_all_completed_output`
- `tests/test_production_recovery.py::test_recover_after_workspace_is_lost_verifies_outputs_and_rechecks`
- `tests/test_production_recovery.py::test_branch_acknowledgement_tampering_rejected_before_output`
- `tests/test_workflow_media_settings.py::test_batch_media_source_used_by_inspection_review_and_generation[project-8]`
- `tests/test_workflow_media_settings.py::test_batch_media_source_used_by_inspection_review_and_generation[workflow-6]`
- `tests/test_workflow_media_settings.py::test_batch_media_source_used_by_inspection_review_and_generation[None-6]`
- `tests/test_workflow_production_review.py::test_branch_review_does_not_approve_and_handles_all_template_routes`

Deferred minor from review: the unit-level DSC callback/no-callback comparison
runs the current implementation twice; a fixed golden fixture would strengthen
future change detection. Independent pre-change benchmark PS/CSV byte hashes and
existing media/DSC assertions provide additional evidence for this repair.

No packaging, release, main merge, commit or push is performed. Existing running jobs
are not hot-patched or restarted; the repair applies to new jobs after reopening.
macOS native performance and physical-printer output are **Not Tested** in this task.
Full application regression and release/native-package gates retain their existing
separate arrangement; the scope here is affected PS/media/production/UI safety.

## References

- [PyMuPDF Document.save](https://pymupdf.readthedocs.io/en/latest/document.html):
  documented garbage collection, duplicate-object/stream handling and deflation.
- [Ghostscript vector devices](https://ghostscript.readthedocs.io/en/gs10.05.1/VectorDevices.html):
  ps2write behavior and resolution/appearance limitations.
