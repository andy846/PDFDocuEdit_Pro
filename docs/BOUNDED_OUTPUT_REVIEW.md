# Bounded production output — owner review

Date: 2026-10-17. Product worktree: `print-composition-v3/PDFdocuEdit_Pro`.
Branch: `codex/deep-search-restore-layout`; HEAD remains `a5cd66db8d071c6db733c1f10e4f926751b83a76`.
Existing M0/M4, PS performance and Windows project-opening work was retained.
No public version change, format bump, dependency, commit, merge, package or release.

## Implemented

- Shared runtime Output Policy for Template Designer, Overlay and Visual Workflow
  (including Batch / Branch). UI defaults: PDF 250 MB, PS 500 MB, 1,000 envelopes.
- Independent system ceilings: 2,000 MB per final PDF / PS; 20,000 pages per part;
  10,000 parts. Actual bytes are checked. Known minimum part overflow blocks review.
- Existing chunks are selected directly into bounded whole-envelope candidates.
  No unlimited combined PDF is created before splitting. Oversize candidates retry
  as strictly smaller envelope sets. A single envelope over a bound fails clearly.
- Existing planners, renderer, qpdf, barcode decoding, media/JDF, Ghostscript,
  full output validation, production journal and atomic publication are reused.
- User naming presets/custom structure, protected six-digit numeric ordering,
  actual physical sheets / envelopes / D-S, matched PDF / PS basenames, final
  source maps, hashes, manifest, control and output summaries. CSV name cells use
  the existing formula escaping helper. Legacy single output layout is retained.
- Policy is bound to signed review. Independent refinement checks canonical part
  numbers, group order, exact envelope coverage and signed partition membership.
- Readable shared settings modal, local preferences, early resolution validation,
  review invalidation, task locking, numeric part chooser, keyboard cancellation,
  screen-constrained sizing and existing wide combo popup.
- Production source runs are frozen per part so media-inserted backs and global
  source pages can be traced without rebuilding a large print plan on the UI thread.

## Files

New headless modules: `composition/production/output_policy.py`,
`output_naming.py`, `packages.py`, `partitioning.py`.
New UI adapters: `composition/designer/output_limits.py`, `output_results.py`.
Modified existing model/generator, media export, review/authorization, Designer,
Workflow and workspace-handoff adapters. The variable parser only gains the
controlled `part` and `group` namespaces. Existing project serializers and PDF
engine are unchanged. README, in-app README and operator documentation updated.

New tests: `test_output_policy.py`, `test_output_packages.py`,
`test_output_limits_ui.py`; converter boundary regression added to
`test_postscript_progress.py`. UI test classification updated in `ci_plan.py`.

## Verification

**459 passed / 0 failed / 0 errors / 0 skipped across 29 unique relevant modules.**

The modules ran in separate processes using the existing regression runner.
Latest reruns supersede earlier module results; counts do not add repeated runs.
Evidence: `build/probes/bounded-output/{final-regression,final-contracts,integrity}`.
Ruff for all changed feature source/tests and `git diff --check` passed.

Coverage includes real Ghostscript interpretation of paired parts, PDF pixel/text
comparison against unsplit output, global I25 98/99/00 across parts, Duplex blank
backs and stock-change blanks, count and actual-byte splitting, single-envelope
failure, cancellation after an accepted candidate, converter termination/reaping,
missing/changed authorization, invalid naming, path budgets, CSV escaping,
Workflow count/field groups, Branch recovery and atomic failure handling.

A fresh independent final reviewer found four P2 boundary issues. Reproductions
failed before fixes and passed afterward: early naming resolution, Overlay source
mapping with media blanks, canonical refinement order, and single flat path budget.
Scratch-space checks and temporary interpretation-PDF cap semantics were also
addressed. The latter uses the system cap, not the user's delivered PDF cap.

Windows Qt offscreen checks: product Light/Dark, normal and 200% scaling, narrow
controls, fixed buttons, screen limits, keyboard and draft validation. Rendered
artifacts are `limits-{light,dark}-{100,200}.png` in the evidence folder.

Final 50,000-envelope synthetic PDF-only benchmark: 50,000 pages, 50 parts of
1,000 envelopes; 131.11 seconds while regression tests also ran. Composer process
peak 99,749,888 bytes; assembler process peak 18,505,728 bytes. Final PDFs total
24,593,678 bytes. This is a simple deterministic synthetic workload, not a
throughput guarantee or a comparison against an idle baseline, complex PDFs,
PostScript conversion or a physical RIP. Earlier run: 106.53 seconds; retained
separately. Evidence: `benchmark-final.json`, `benchmark-final.log`.

## Compatibility and limitations

- Existing `.pdcx` / `.pdflow` structures remain unchanged. Runtime policy is stored
  in reviewed job state/local preferences. Old prepared Batch signatures require
  fresh checking; old saved projects still load. No old approved boolean becomes
  a new authorization grant.
- Headless callers without policy retain original naming and system-only limits.
- Existing Template Direct Content decode-coverage limitations remain explicit;
  no unsupported all-barcode verification is claimed.
- Exact total PS/RIP spool size is unknown before native conversion. Review checks
  a minimum free-space floor; each candidate uses a conservative chunk-based
  scratch estimate and exact final byte checks. Disk/quota can change afterward.
  Temporary-file monitoring may briefly overshoot; it is not a filesystem quota.
- All parts must fit the destination volume before atomic set publication.
- In-progress cross-restart candidate resume is not offered. Existing verified
  completed-package recovery remains covered by the recovery suite.
- macOS native execution, installer/update packages and physical printer/RIP
  acceptance: **Not Tested this task**. Full release regression remains separate.

## Status

Implementation complete; ready for owner review. No remaining automated failures.
Owner can test **Output limits & file naming…** in Template Production, Overlay
Production results or the Visual Workflow toolbar. This task stops before release.
