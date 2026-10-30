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

Focused verification: 15 core tests and 16 Quick UI cases (including three
sample-selection cases, a real child blocked in rendering, and shutdown with
a paused-search dependency after the close deadline) passed. Eight related modules ran in fresh processes:
139 tests passed, covering Workflow core/UI, detection profile UI, close status,
source/CI contracts, PDF engine and packaging source checks. Whole-repository
Ruff and the documentation links check passed.

UI smoke used the offscreen Qt backend. A 20,000-page / 20-field job including
the first bounded results query took 72.082 s; a 20 ms UI timer produced 3,601
ticks, with maximum gap 47.447 ms. A 200% DPI smoke with 1,000 pages / 20 fields
and explicit Windows font availability took 7.412 s, with maximum timer gap
38.610 ms. Light/dark, 1280×800 and 960×640 layouts retained visible footer
controls and keyboard focus. These checks are not manual GUI acceptance or a
latency guarantee for every PDF page. The temporary job directory was removed.

The full **225-module** run completed: **3,563 passed, 8 failed, 6 skipped,
0 errors** (3,577 cases). This was not a single all-green run. The five failing
modules were rerun without weakening tests or product gates: **57 passed**.
The original logs/JUnit results remain unchanged. After the final path-alias
protection fix, Quick core/UI plus Workflow core also ran: **55 passed**,
including all 30 new feature cases.
The final shutdown ordering fix then passed the Quick UI, Deep Search shutdown
and close-status group: **44 passed**. The additional cross-tool deadline case
brings new feature coverage to **31 tests**. In that case the search dependency
is controlled; the existing real search shutdown tests also ran in the group.
These final targeted checks are separate from the original complete-run counts.

One initial failure was `test_published_ps_first_open_reuses_interpreted_preview[workflow]`:
Windows reported WinError 32 (temporary production PDF occupied). The complete
five-case module independently reran successfully in 14.83 s. Both logs are
retained; the original failure is not erased and the transient lock's exact
cause has not been established. The PS production path was not changed.

Two further full-run failures were isolated to test context:

- `test_mac_update_ui_never_starts_windows_update`: the test expects no managed
  update root, whereas the suite inherited the QA isolation root. All 13 module
  tests passed in 2.29 s after removing only that environment override. This is
  simulated macOS behavior on Windows, not a macOS platform test.
- `test_actual_windows_credential_manager_roundtrip`: the filesystem sandbox
  refused Windows Credential Manager. The existing 19-test module passed in
  0.74 s outside that sandbox, using its random `qa<UUID>` namespace and fake
  approval data. No actual account credentials were read or altered, and this
  is not a real account login acceptance result.

`test_workflow_pdf_operations.py` hit the existing explicit output-path length
guard; its 7 tests passed in 3.28 s using fresh shorter `build/probes/er-p`.
`test_workflow_branch_engine.py` had 4 initial pre-review status/approval
failures; all 13 cases passed in 61.11 s using fresh `build/probes/er-b`.
The shorter path context is consistent with the path-limit finding, but the
original branch assertion alone does not establish a unique cause. No
production rules, approval conditions or path limits were altered.

The six skips are three native macOS cases (bundle permissions/links, Keychain,
signed arm64 installation) and three symlink/junction cases unavailable in the
test host. They remain skipped, not treated as passed.

The final alias regression uses an isolated virtual home inside its fixture;
it proves a `~` destination cannot resolve past the source-overwrite guard.
No real HOME/USERPROFILE or user document was changed.

## Reproduction commands and Git

Use the repository's `.venv-dev`. Test TEMP/TMP, the optional
`PDFDOCUEDIT_UPDATE_ROOT`, and Qt settings were isolated under
`build/probes/extract-region-2/`. UI smoke used `QT_QPA_PLATFORM=offscreen`;
`QT_QPA_FONTDIR=C:\Windows\Fonts` provided real system glyphs for visual checks.

```powershell
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction.py
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction_ui.py
.\.venv-dev\Scripts\python.exe scripts/regression_suite.py --group all --output build/probes/extract-region-2/regression
.\.venv-dev\Scripts\python.exe -m pytest -q tests/composition/test_postscript_preview_handoff.py
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_macos_parity.py
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_private_auth.py
.\.venv-dev\Scripts\python.exe -m ruff check .
.\.venv-dev\Scripts\python.exe build/probes/extract-region-2/benchmark.py
.\.venv-dev\Scripts\python.exe build/probes/extract-region-2/ui_smoke.py
```

The eight-module focused run used `scripts.regression_suite.run`, with one
process per module; its exact list/results are in the local
`focused-isolated/result.json`. Explicit fresh `--basetemp` directories were
used for targeted/rerun pytest commands. A combined multi-module GUI attempt
was interrupted without a result; it was replaced by the fresh-process run,
and is not counted as passing evidence.

Product checkpoints on local main: `7e8e061` (selected-page storage and exports)
and `52fcd19` (visual editor/lifecycle/handoff), followed by the verified preview
cancellation and final QA addendum. No branch/worktree, push, release, version
change or dependency change was made. Original `BOCHK.pdmp` remains untracked
and untouched. Fresh-context review findings on raster/text staleness were
fixed and covered by actual displayed-image and stale-text tests.

Existing files changed: `composition/worker.py` (guarded worker dispatch),
`composition/designer/mailpiece_region.py` (shared optional view callbacks),
`core/viewer.py` (routing/shutdown), `ui/close_lifecycle.py` (worker accounting),
and `scripts/ci_plan.py` (new UI regression membership).
New runtime files: `core/text_extraction.py`, `dialogs/quick_text_extractor.py`,
`ui/text_extraction_controller.py`. New tests: the two `test_quick_extraction`
modules. Documentation: this record and `EXTRACT_TEXT_REGION.md`.

## Not tested

Live account login, actual customer PDFs,
manual Windows GUI UAT, macOS, and a newly packaged build have not been tested
for this feature. Existing release acceptance records do not count as acceptance
of these changes. No installer, update package or release is produced.
The performance observations exclude Editor opening and current-engine snapshot
capture. Startup comparisons and complex customer-page performance are unmeasured.

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

## Same-screen workbench revision — 2026-10-28

Baseline: local `main`, `2a2f1d776626f6bb37ab432ae54422255b141e03`.
Only the pre-existing untracked `BOCHK.pdmp` was present; it was not read or
modified. No branch, worktree, version/dependency change, push or release.

### Implementation

- Quick-only `dialogs/extraction_workbench.py` reuses the original widgets in a
  fields/PDF/properties layout above a full-width results table. Raw/Clean is in
  Text preview; advanced rules collapse. QSettings retains only visual state.
  First-use geometry is approximately 92% of the available screen; restore and
  live monitor/DPI signals use the existing screen-bounds helper. Splitter
  positions are restored once, not reset on every resize.
- Quick-only `dialogs/extraction_canvas.py` provides explicit New region drawing,
  Esc cancellation, numbered named badges, active frame/handle, visibility and
  overlap selection. Labels are clamped visually without changing millimetres.
  Duplicate offsets within page bounds; the final Quick region can be deleted.
- `dialogs/quick_text_extractor.py` reuses the same Region/ExtractionSpec, SQLite,
  workers, formats and Workflow handoff. Current full/sample results navigate to
  source pages/fields; sample freshness remains separate from export eligibility.
  Preview-page raster identity blocks drawing on a mismatched displayed page.
  Both save-directory helpers now receive their owning widget.
- `workflow/regions_ui.py` exposes optional canvas/empty-draft/selection hooks and
  widget references only. Default Workflow layout and minimum-one-region behavior
  remain unchanged. `scripts/ci_plan.py` registers the new UI module.

### Verification evidence

Local evidence is under `build/probes/extract-workbench/`. Ten relevant modules
ran in separate processes using `scripts.regression_suite.run`: **177 passed,
0 failed/errors/skipped** before the final review additions. The workbench module
was then expanded from 10 to 14 cases; its final run passed **14/14**. Together
with the other nine modules this covers **181 distinct passing cases**, not a
claim that the entire repository regression suite ran for this UI revision.
The existing 16-case Quick UI module was also rerun after review fixes.

Covered modules: `test_quick_extraction`, `test_quick_extraction_ui`,
`test_quick_extraction_workbench_ui`, `test_workflow_core`, `test_workflow_ui`,
`test_close_status`, `test_ci_plan`, `test_source_contract`, `test_pdf_engine`,
and `composition/test_mailpiece_profiles_ui` (all under `tests/`).

New coverage includes empty/draw/Esc/delete-last/Undo; 13 regions and repeated
selection/redraw; duplicate-one-Undo; overlap chooser; long edge badges/theme;
maximized/geometry/splitter memory; removed-monitor and live monitor/DPI signal
simulation; sample navigation without export; stale sample rejection; old-raster
drawing rejection; full resize-handle hit area; custom-page navigation; and
Export button/helper invocation followed by actual XLSX worker output.

An independent read-only review found a cancelled-raster race, sample-navigation
rejection and a partially inactive resize handle. All three were reproduced in
failing tests before correction, then passed. A wide-table test initially found
the horizontal scrollbar reduced the complete visible row count. The height
budget now includes that scrollbar and frame; the test uses twelve fields.
Earlier failed/combined GUI attempts are retained and are not passing evidence.

Synthetic 30-page, 12-field scans with real worker/SQLite results produced:

| Logical window | DPI scale | Light full rows | Dark full rows |
| --- | --- | ---: | ---: |
| 1280×800 | 100% | 8 | 8 |
| 960×640 | 100% | 6 | 6 |
| 1280×800 | 200% | 8 | 8 |
| 960×640 | 200% | 6 | 6 |

These are actual table viewport height / unchanged row-height measurements with
a horizontal scrollbar. Footer bounds were checked. Screenshots were inspected
for both themes; evidence is in `visual-standard.json`, `visual-hidpi.json` and
the corresponding PNGs. They are Windows **offscreen Qt** checks with installed
Windows fonts, not physical monitor/DPI acceptance or packaged GUI UAT.

Commands (TEMP/TMP and update runtime root isolated under the probe directory;
`QT_QPA_FONTDIR=C:\Windows\Fonts` for offscreen tests):

```powershell
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction_workbench_ui.py --basetemp build/probes/extract-workbench/workbench-final-02
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction_ui.py --basetemp build/probes/extract-workbench/legacy-final-02
# QT_QPA_PLATFORM=offscreen; QT_SCALE_FACTOR=1, then 2:
.\.venv-dev\Scripts\python.exe build/probes/extract-workbench/smoke.py standard
.\.venv-dev\Scripts\python.exe build/probes/extract-workbench/smoke.py hidpi
.\.venv-dev\Scripts\python.exe -m ruff check .
.\.venv-dev\Scripts\python.exe scripts/verify_source.py
git diff --check
```

The ten-module harness's exact per-module results are in `regression/result.json`.
No extraction engine, production authorization or export-format code changed;
no new speedup or large-dataset benchmark is claimed for this layout-only revision.
Selection/layout changes avoid launching extra extraction workers; table paging
remains 100 rows and previews remain lazy. Existing core geometry/rotation/CropBox,
atomic export and lifecycle tests passed in the focused run.

### Remaining manual acceptance

- Native Windows Save dialog: an isolated synthetic interactive probe could not
  obtain a targetable desktop window. It was stopped; logs were retained. The
  automated button test substitutes only the filename chooser, then performs
  the real export. Native chooser/overwrite-confirmation interaction remains
  **Not Tested**, rather than inferred from that test.
- Physical multi-monitor moves, actual system 100%/200% DPI, human keyboard/tab
  usability, actual customer documents, packaged Windows and macOS: **Not Tested**.
- The owner's running application was not closed or replaced by this task;
  a normal restart is required to load modified Python modules.

Owner UAT: reopen Extract Text on a text PDF; confirm no default box; draw 12
named fields, try overlapping/whole-page duplication, rename long fields, use
Only selected via All regions, Esc and Undo/Redo. Resize/reopen/maximize and move
between monitors. Check eight/six complete rows at the specified logical sizes,
horizontal scroll, result focus/restore, sample/full page-field navigation and
Raw/Clean. Finally use the native Export chooser for XLSX/CSV/TXT, confirm explicit
overwrite, cancel an active job, and check safe close and Workflow handoff.

## Portrait A4 and one-action Excel revision — 2026-10-29

This supersedes the preceding upper-workspace/full-width-bottom-table layout.
The owner approved the left portrait PDF / right settings and results mockup.
Baseline: D-drive local `main`, `0d120faf31dd2ce1edce70317195a8e7259227b1`.
No version, dependency, extraction model/engine, SQLite/export format, production
authorization, branch/worktree, push or release change. The existing user app
was left open; `BOCHK.pdmp` was neither read nor modified.

### Changes and safeguards

- `dialogs/extraction_workbench.py`: full-height left PDF (~48% initial width),
  right settings/results split and right-side footer. Existing scene, named
  fields, page fitting, pan, zoom and editing remain shared. Geometry/advanced
  controls collapse; common field properties remain visible. QSettings v3 imports
  only v2 window geometry, never old splitter axes/collapse flags. Main, settings
  and right vertical splits retain independent state. Focus/collapse restores.
- `dialogs/quick_text_extractor.py`: default optional First 10 trial with explicit
  Sample/Complete/stale/failure status. Primary **Extract & Export Excel…** fully
  scans selected pages then opens the save chooser, or reuses a current full DB.
  Trial results never qualify, even if the trial covered every selected page.
  The continuation runs after the result-row worker, not while the host would
  reject an overlapping request. Repeated clicks, scan failure/cancellation,
  close, source invalidation and cancelled chooser do not produce unintended
  output. Source/config are checked before the chooser and by export afterwards.
  The Excel primary rejects non-XLSX names without changing the chosen file.
- **More** retains Extract only, complete-result XLSX/CSV/TXT export and Workflow
  handoff. No new publication path: overwrite confirmation, source protection,
  atomic output, safe late commit receipt and worker cleanup remain existing.
- Tests: existing Quick/workbench modules retain prior lifecycle/geometry checks;
  new `tests/test_quick_extraction_export_ui.py` uses real worker scans/SQLite/XLSX
  and substitutes only filename selection. `scripts/ci_plan.py` includes it.

### Results

The isolated 11-module focused regression run passed **192 tests, 0 failures,
errors or skips**, including Quick extraction core/UI, workbench, one-action
export, Workflow core/UI, close status, CI/source contracts, PDF engine and
detection-profile UI. After adding product-wide stylesheet and v2 migration
coverage, the workbench module passed **16/16**; after adding an all-selected
trial case, the export module passed **11/11**. This yields **194 distinct
passing cases** across those modules, not a full-repository regression claim.
Early expected RED runs and subsequent passing logs remain under
`build/probes/extract-portrait/`.

New tests exercise actual XLSX values/row counts for a 15-page source, leading
zeros, trial-before-export versus no trial, stale-rule rescan, full-DB reuse,
duplicate clicks, chooser cancellation, corrupt input, source changes before or
inside the chooser and rejecting `.csv` on the Excel-only action. Existing generic
CSV/TXT tests remain in the core module. Native chooser interaction itself is
still Not Tested; automated selection uses a substituted chooser, with real
export workers afterwards.

Independent final read-only review reported no Critical, Important or Minor
findings. Additional real-worker probes covered a five-page trial covering the
entire source, repeated primary requests during rows loading, and cancel/close/
source change during that rows stage. Closing inside the substituted chooser
also preserved the target. These probes are retained in `review/probe.log` and
`review/safety.log`; they are separate from the maintained-test count above.
The reviewer did not judge native chooser interaction, physical monitors/DPI,
macOS or printing. Those remain untested or outside this UI change, not inferred
passes. Operator documentation was checked separately against final behavior.

Synthetic 30-page / 12-field worker scans were inspected with **the same global
stylesheet as the application**, not palette-only Qt controls:

| Logical client size | Scale | Light full rows | Dark full rows | PDF viewport (w×h) |
| --- | --- | ---: | ---: | --- |
| 1280×800 | 100% | 8 | 8 | 603×736 |
| 960×640 | 100% | 6 | 6 | 450×576 |
| 1280×800 | 200% | 8 | 8 | 603×736 |
| 960×640 | 200% | 6 | 6 | 450×576 |

Rows are measured from the actual table viewport with unchanged font/row sizing
and a horizontal scrollbar. Footer bounds and full-height portrait viewport
were asserted. PNGs and measurements are `visual-styled-standard.json`,
`visual-styled-hidpi.json` and their specifically named screenshots. The earlier
palette-only probe showed 11/7 rows and is not the final styled acceptance data.
These are offscreen Windows Qt checks using Windows fonts and synthetic PDFs;
physical monitors, actual system DPI moves, packaged Windows, macOS and customer
documents remain Not Tested. No startup/throughput speedup is claimed.

Commands (TEMP/TMP and runtime root isolated below the probe directory;
`QT_QPA_FONTDIR=C:\Windows\Fonts`):

```powershell
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction_workbench_ui.py --basetemp build/probes/extract-portrait/green-styled-layout
.\.venv-dev\Scripts\python.exe -m pytest -q tests/test_quick_extraction_export_ui.py --basetemp build/probes/extract-portrait/green-export-03
# The same scripts.regression_suite.run harness, one process per named module:
# exact module names/counts/times are in build/probes/extract-portrait/regression/result.json.
# QT_QPA_PLATFORM=offscreen; QT_SCALE_FACTOR=1, then 2:
.\.venv-dev\Scripts\python.exe build/probes/extract-portrait/smoke.py styled-standard
.\.venv-dev\Scripts\python.exe build/probes/extract-portrait/smoke.py styled-hidpi
.\.venv-dev\Scripts\python.exe -m ruff check .
.\.venv-dev\Scripts\python.exe scripts/verify_source.py
git diff --check
```

Manual UAT: after a normal restart, open a portrait A4 text PDF and draw fields.
Check the larger left preview, right properties and table, divider/geometry
memory, More actions and keyboard access. Try 10 pages if desired, then use the
primary action and verify all selected pages in Excel. Try custom pages, cancel
the save chooser, edit a field and export again, test native overwrite confirmation
and close/cancel during a scan. Repeat with a landscape/rotated CropBox PDF,
physical screen/DPI changes, and Workflow handoff. The software checks do not
replace operator review of extracted content.

## Post-v3.1.2: completed export left at 1/5 (local fix, 2026-10-29)

Reproduced with five selected PDF pages and real worker/XLSX output: all five
values were present, but the progress bar remained at 1/5. Export reports row
progress at row 1, 101, etc.; it lacked a final notification after publication.
The shared XLSX/CSV/TXT export now reports N/N after the atomic output context
successfully commits, retaining the existing receipt and cancellation ordering.
No extraction, output-format, version or production-authorization rules changed.

New tests failed before the fix (three export formats and two real-worker UI
paths). Source-change rejection tests already passed and remain passing. The
UI tests cover both direct extraction/export and reuse of a complete scan, and
read the resulting workbook to verify all five values as well as final progress.

Windows `.venv-dev` results, each UI module in a separate process:

| Command after `python -m pytest` | Result |
| --- | --- |
| `tests/test_quick_extraction.py -q` | 21 passed |
| `tests/test_quick_extraction_export_ui.py -q` | 13 passed |
| `tests/test_quick_extraction_ui.py -q` | 16 passed |
| `tests/test_quick_extraction_workbench_ui.py -q` | 16 passed |

Total: 66 passed, 0 failures/skips. Ruff on changed Python files, source
verification and `git diff --check` passed. TEMP/TMP and pytest basetemps were
isolated under `build/probes/extract-progress/`; red/green logs are retained there.
The UI save chooser is controlled in tests; actual file generation and reading
use the real worker and exporter. Native save-dialog interaction, packaged
Windows, macOS and customer documents were not tested for this patch. The full
release suite was not rerun. This is a local main fix, not a changed v3.1.2 asset;
no version bump, push, packaging or publication was performed.
