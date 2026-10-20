# Annotate & Edit reliability — implementation and owner review

Date: 2026-10-20. Approved plan: [implementation plan](plans/2026-10-20-annotate-edit-reliability.md).

## Baseline and scope

Workspace: `D:\Python_Project\PDFdocuEdit_Pro`, `.venv-dev`.
Implementation branch was `codex/deep-search-restore-layout`; its base HEAD was
`1d48fa9e396ae3b23ec198e5c1ce9c11e42989d4`.
The published v3.0.10 source is `796cd7dfbdac884f495a31c521c22e4f4f3cce50`;
the reviewed remote main was `cfc19778e98a5ae86b967a864f6b6b0c8d34a5c8`.
This work does not merge those lines or change the public version.
The owner's pre-existing untracked `BOCHK.pdmp` is untouched.
At implementation handoff, no branch, worktree, commit, push, installer or release
had been created. The subsequent owner-authorized local main consolidation is
recorded below.

## Findings and implemented changes

| Area | Evidence / correction |
|---|---|
| Open bootstrap | A failed replacement could leave the new engine installed without restoring the previous session. Retain engine, history, form draft and view state until initialization succeeds; retire failed engines through existing reader leases and restore the actual draft preview on rollback. Empty failed placeholders close. |
| Render lifecycle | Refill paused readers when their final pause ends. Reject stale/empty render keys safely, retry a failed page once, then show Retry / Close. Explicit Retry starts a new bounded attempt. Successful load feedback waits for actual pixels. Comparison-pane Close routes to the document displayed there. |
| Stamp geometry | The fixed 0.35 ratio was inconsistent with the native stamp's 190:50 appearance. Fit the visible rectangle using the intrinsic ratio, then derotate once. Apply appearance orientation separately. Custom stamps use the existing editable image placement path. |
| Image / signature resize | Existing translation updates were incorrect for quarter turns / negative matrix axes. Apply the full page-space affine delta, including translation, to the existing placement matrix. |
| FreeText / Callout | Carry visual rotation into native annotation and system-font appearance construction. Compute callout points in visible page coordinates before derotation. |
| Watermarks | New ordinary PDF content with independently owned placement streams, embedded resources and versioned metadata. Position presets, mm offsets, uniform scale, arbitrary angle, opacity and current-page background preview. Select, edit properties, move, resize or delete after Save / Reopen. |
| Small windows | Use existing responsive scrolling and fixed actions. Reveal the entire focused watermark spin box, including its buttons, at narrow logical sizes. |

**The original intermittent cross-document blank-tab incident has not been naturally
reproduced.** The lifecycle defects above are confirmed by fault injection and
regression tests; they do not establish a unique cause of the reported incident.
No source-file corruption was observed in the exercised discard/reopen sequence.

## Source map and maintenance rules

- `core/viewer.py`: reversible queued installation, first-pixel load feedback,
  comparison close routing and selected-watermark editing. Preserve mutation
  transactions and session/revision checks across nested dialogs.
- `core/reader_lifetime.py`, `ui/pdf_canvas.py`: pause/resume, bounded retries,
  stale-result rejection and preview reader leases. Never force-unlock the global
  document lock, clear the global pool or close a leased document.
- `ui/page_view.py`: persistent page error actions, hidden after successful render.
- `core/annotations.py`: compatible annotation entry points and watermark routing;
  optional visual rotation retains existing callers.
- `core/page_images.py`: oriented insertion and shared affine placement delta.
- `ui/page_overlay.py`, `ui/context_panel.py`: aspect-preserving content selection,
  geometry editing and watermark properties routing.
- New `core/watermarks.py`: `WatermarkSpec`, content creation, ownership checks,
  listing, current properties, geometry changes and removal.
- `dialogs/annotation_dialogs.py`: existing watermark dialog extended with controls,
  preview and edit mode; `ui/watermark_preview.py` is the new coalesced worker.
- New tests: `test_render_recovery.py`, `test_stamp_rotation_visual.py`,
  `test_watermark_placements.py`, `test_watermark_dialog.py`.
- `tests/test_tools_port.py`: retain legacy success wording while asserting that
  loading is not announced before rendered pixels arrive.

### Watermark compatibility

The private version-1 metadata is on the owned content stream. Original image
bytes are embedded; reopening does not require the image's original path.
Indirect references survive ordinary garbage-collecting saves. Placement,
recursive resource and image-asset fingerprints protect destructive edits after
external changes. Malformed metadata is ignored for editing and does not prevent
ordinary PDF display. Shared streams use copy on write.

Watermarks remain printable with annotations hidden. Existing flattened/legacy
watermarks are not inferred to be editable. External stream merging or resource
rewriting may invalidate ownership and intentionally block editing. The product's
`insert_pdf` duplication path is tested; arbitrary external rewriting is not
guaranteed. No `.pdcx` / `.pdflow`, production authorization or PDF engine change.

Preview copies one current page under the document lock in a worker, then reuses
that snapshot. Changes are debounced and coalesced; closed-dialog/stale callbacks
are ignored. Batch content creation shares font/image resources and hash memoization.
Diagnostics contain operation identities, counters and exception classes/frames,
not document text, customer fields, passwords or account information.

## Verification

Evidence is local under `build/probes/annotate-edit-20261020/` and is not committed.

| Check | Result |
|---|---|
| Full isolated regression plus complete reruns of 22 affected modules | 215 modules; **3,070 passed, 4 skipped, 0 remaining failures/errors**; 3,074 cases total |
| Final affected-module run | **422 passed**, no skips/failures |
| Final watermark dialog, standard scaling | **4 passed** |
| Final watermark dialog, 200% Qt scaling | **4 passed**, both themes; focused offset control and fixed Apply action reachable |
| Ruff, all modified/new Python sources and tests | Passed |
| `git diff --check` | Passed; normal LF/CRLF notices only |
| Rotation / persistence | Synthetic asymmetric pixel checks at 0/90/180/270; native/custom stamps, images/signatures, FreeText, Callout, CropBox, save/reopen, move/resize, resource ownership, Undo/Redo |
| Original five-page image-only PDF | Three discard/reopen cycles, two tab closes and one whole-viewer close; all five pages rendered, another PDF opened, source SHA-256 unchanged |
| Windows frozen QA | Isolated PyInstaller editor harness using product spec/resources; both themes and 100%/200% scaling, annotation Undo/Redo and saved editable watermarks, injected render failure/retry |

The full run initially found two failures: an empty legacy render key caused a
Qt-slot abort, and a status test assumed success before first pixels. The guard,
compatible message and timing assertion were corrected. Both complete modules
passed in the final 22-module run. Initial logs are retained. Consolidated results
replace affected rows with their complete reruns; this is **not** a claim of one
single all-module run against a frozen final source snapshot.

The final narrow-focus assertion initially failed at 200%; the local dialog
correction passed at both scales. Four skips are three native macOS gates
(bundle permissions, Keychain, signed arm64 install/update) and a file-symlink
permission case unsupported by this Windows host.

Commands (PowerShell, repository root):

```powershell
.\.venv-dev\Scripts\python.exe -m scripts.regression_suite --group all --output build/probes/annotate-edit-20261020/full-regression
# The exact 22-module list and per-module logs are in final-regression.log/result.json.
.\.venv-dev\Scripts\python.exe -m pytest tests/test_watermark_dialog.py -q
$env:QT_SCALE_FACTOR='2'
.\.venv-dev\Scripts\python.exe -m pytest tests/test_watermark_dialog.py -q
# Changed-file Ruff command is recorded in the execution history; includes all files in the source map.
.\.venv-dev\Scripts\python.exe -m ruff check core/annotations.py core/page_images.py core/reader_lifetime.py core/viewer.py core/watermarks.py dialogs/annotation_dialogs.py ui/context_panel.py ui/page_overlay.py ui/page_view.py ui/pdf_canvas.py ui/watermark_preview.py tests/test_tools_port.py tests/test_render_recovery.py tests/test_stamp_rotation_visual.py tests/test_watermark_dialog.py tests/test_watermark_placements.py
git diff --check
```

The frozen QA uses a probe-local spec and `visual_qa.py`; it is not the release
candidate or account-login validation. Auth and Composition are disabled only in
that isolated harness. Offscreen screenshots explicitly load Segoe UI because
that Qt plugin has no Windows font database. No installed product settings change.
At 200% the offscreen screen supplies a very small logical area: scrolling is
required. Physical Windows monitor / DPI transitions and macOS remain **Not Tested**.
Physical printers/inserters and exhaustive customer fonts remain **Not Tested**.

### Measured performance

Synthetic 2,000-page text PDF: watermark placement **6.422 s**, serialization
**5.935 s**, resulting PDF **2,158,095 bytes**, one additional shared font resource.
Windows process peak working set **77,299,712 bytes**; final working set
76,034,048 bytes (initial 56,279,040 bytes). First/last-page reopen and watermark
removal preserved source content. See `performance.json` and `performance_qa.py`.

No baseline speed comparison or end-to-end UI-latency benchmark was performed.
Bulk application retains the existing synchronous mutation path and may pause
the UI on very large jobs. Preview is background work; it does not prove bulk
application responsiveness. No claim of a measured speed improvement is made.

## Owner UAT

1. In the D-drive development program, open the image-only checklist PDF. Rotate
   90°, close the tab and choose Discard. Reopen it, then open a different PDF.
   Repeat with whole-program close / restart and Windows double-click opening.
   Confirm all pages appear and the original rotation remains unchanged.
2. On a copy, test 0/90/180/270° pages, portrait/landscape and cropped pages.
   Drag native/custom stamps, images/signatures, FreeText and Callout at several
   zoom levels. Compare visible preview, final position, aspect and text direction.
3. Add text/image watermarks with an off-centre anchor, offsets and fractional
   angle. Compare preview, Apply, Undo/Redo and Save/Reopen. Select one watermark,
   edit properties, drag/resize and delete it; verify other placements survive.
   Rotate/crop the page and open properties without changes to check preservation.
4. Exercise light/dark themes, 960×640, 200% system scaling and keyboard navigation.
   Scroll overflow; Apply/Cancel must remain reachable. Check comparison panes.
5. If a blank page recurs, retain the process and logs before restarting. Capture
   whether Retry works, whether another PDF opens and whether an error panel is
   visible. Do not overwrite the source as a diagnostic step.

Status: implementation and automated checks complete; ready for owner UAT.
The unique original incident cause and physical/platform validation remain open.

## Local main consolidation

The owner subsequently requested one active version on `main`. GitHub main and
local main were both `cfc19778e98a5ae86b967a864f6b6b0c8d34a5c8`, an ancestor
of the verified D-drive development line. All 16 source/test fingerprints matched
the recorded final QA snapshot; the 83 new reliability tests passed again before
checkpointing. The intended integration is a local fast-forward, with no conflict
resolution or product-source change. `AGENTS.md` identifies D-drive main as the
single daily development/test entry.

The clean C-drive checkout previously holding main is retained at its original
commit as a detached rollback checkout. It is not deleted or used for launch.
Local integration does not update GitHub main or the already-published v3.0.10
package. Public version, releases, owner profiles and build evidence remain
unchanged. Final commit IDs and post-merge verification are recorded locally in
`build/probes/annotate-edit-20261020/main-integration.json`.
