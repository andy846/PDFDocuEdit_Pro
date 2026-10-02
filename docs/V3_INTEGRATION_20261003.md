# V3 consolidated development line

2026-10-03 (Hong Kong). This is a development integration, not a V3 release.

## Canonical checkout

Continue all PDF Workspace and Document Designer development on
`feature/print-composition-v3` in `D:\Python_Project\PDFdocuEdit_Pro`.
The two earlier worktrees remain detached snapshots; their ignored builds and
runtime files are retained, including the worktree used by the running application.
They are not separate development branches.

Enable Designer for development using `PDFDOCUEDIT_ENABLE_COMPOSITION=1`.
Public release metadata follows the incoming stable v2.5.16 baseline.
V3 packaging, its public version change and a new release remain deferred.

## Integrated updates

The full history through `945713c` is merged, rather than copying only the ruler.

- PDF ruler: paper-distance measurements in mm/cm, per-page known-length or
  1:N calibration, saved paired line/caption annotations, editable endpoints,
  recalculated labels and undo/redo. Page operations retain calibration.
- Deep Search: individual hits/snippets, file/word/source filters, hit-page opening,
  printable HTML and detailed CSV reports, background storage/export.
- PDF Overlay tool: individual/folder/current-document inputs, background
  preflight, before/after preview, pairing/layer/alignment/rotation/mm offsets,
  per-page cancellation, atomic outputs and per-file CSV results. It also uses
  unsaved PDF edits. This is separate from Designer envelope overlays.
- CI/release workflow: affected tests on branch pushes, full automated groups
  on PR/merge, relevant UI/platform jobs, and explicit local `--run-tests`.

Designer templates, production, mailpiece detection/review, barcode features,
geometry/snapping, automatic glyph fallback, the persistent mode switch and
the restrained splash are retained. Composition stays independent of PDF UI.

## Integration repairs

- Public PDF open methods switch to PDF mode after any required discard prompt.
  Deep Search can remain open while changing modes; opening a hit returns to
  PDF Workspace and navigates to its page without discarding Designer state.
- CI discovers nested Composition tests, selects its GUI/platform jobs correctly,
  prepares pinned assets in affected/UI jobs and keeps the existing 100-record
  composition benchmarks. Designer interaction tests belong to the UI group.
- PyInstaller Composition assets/dependencies and development build flags are
  retained alongside the newer stable release metadata.

## Verification

- 100 distinct targeted tests passed: ruler, detailed search/reporting, ordinary
  Overlay engine/UI, task cancellation, mode switching, scoped CI planning,
  source metadata and release/build-script contracts.
- 5 related mode/ruler/hit-navigation/narrow-window cases passed again at 200%
  scaling, including light and dark themes.
- Ruff on changed Python files and `git diff --check` passed.
- Full local regression, Windows packaging and remote CI were not rerun.

## Recovery and retirement

`backup/v3-before-integration-20261003` points to `f1ff941`.
`backup/pdf-tools-before-integration-20261003` points to `945713c`.
Before removing old local measurement/search/CI branches, their tips are also
kept as `backup/measurement-calibration-20261003`,
`backup/deep-search-report-20261003`, and `backup/ci-release-workflow-20261003`.
The calibration commit was squash-merged upstream; its functional files match
the incoming version even though the original commit is not its ancestor.

GitHub main, release tags and remote feature references are not changed by
this local integration. Existing running processes are left open; save work
and reopen the app to load the consolidated code.
