# Merge PDFs workbench — development delivery

Date: 2026-10-03. Base checkpoint: `b47fe0c`. This update does not change the public version or certify a Windows release build.

## How to use

- Any existing Merge PDFs entry opens one persistent **Merge PDFs** tab in PDF Workspace. Repeated entry focuses that tab; use Merge menu → **New list** to start another list.
- Add PDF files, a folder (optionally including subfolders), or selected open PDF documents. Each added batch uses filename natural order and appends to the existing list. Duplicate source paths/revisions are skipped; **Duplicate entry** deliberately repeats a source.
- Drag selected rows to reorder; use Up/Down, top/bottom, natural/added/reverse sorting, Remove and Duplicate. Selection remains intact after a group move. Undo/Redo applies to list and page-selection edits.
- Select rows and apply All, Custom range (`1,3,5-8`), Odd or Even pages. Batch selection changes validate every selected item before committing. Invalid, reversed, empty or out-of-range expressions are rejected without silently clipping pages.
- Preview **Source** pages or the actual **Merge order**. The latter shows output/source page numbers. Page navigation, Fit page/width, pan and zoom are available; each source retains its page and view state. Render only requested pages, with a six-image cache and stale-result protection.
- Use **Review sources** for recheck, explicit confirmation after source changes, or Locate file. Missing/corrupt/password-required files and invalid selections block generation. Changed revisions remain Needs review until explicitly confirmed, even after another recheck.
- Choose the output PDF. Deep compression remains optional and off by default. Sources, captured inputs and open PDFs are protected against output overwrite. Other existing destinations require confirmation.
- Merge runs in a background worker, with Checking/Merging/Saving/Validating progress and safe-checkpoint cancellation. Switching to another PDF or Designer does not cancel it. The list is frozen for this run.
- Results offer Open merged PDF, Send to Designer, Show in folder, Export page map and Merge again. Designer handoff uses the existing service after the output-opening task has finished; no automatic barcode or grouping acceptance is added.

## Persistence and architecture

- **`.pdmerge`** is versioned JSON (`merge_version: 1`), containing item identity, order, page selections, source fingerprint, source references and output options. It stores no passwords, rendered pages or live job state.
- Normal disk inputs use relative paths where practical. Applied unsaved edits from an open PDF are captured as a private snapshot; saving copies snapshots into an adjacent **`.assets`** directory with content-addressed filenames and digests. Keep the list and assets together when moving them.
- Reopened sources are checked in the background. Snapshot digests are checked; changed/missing sources need review or locating. There is no automatic execution or restart restoration.
- Save/Discard/Cancel protects unsaved lists. Save completes asynchronously before the requested close/new/open/exit continues. Exit cancellation leaves running jobs and other work intact; accepted shutdown cancels work and waits for safe cleanup.
- `core/merge.py` exposes Qt-independent `MergeItem`, `MergeSpec`, `MergeResult`, `merge_pdf_items`, strict page selection and list serializers. `core.tools.merge_pdfs` keeps its existing signature and Path result as a compatibility wrapper.
- Whole-document inputs use the existing native insert path. Selected-page inputs use contiguous runs and reconstruct links across selected pages. Internal links to excluded pages are removed and reported; URI links, applicable annotations, rotation and page measurement metadata are retained. Signature validity is not preserved by merging and is reported as a warning.
- `DocumentWorkspace` has independent tool-tab registration/activation/close routes; Merge is not a DocumentSession. Widget identity keeps PDF sessions correct after mixed-tab movement/removal. `ui/merge_controller.py` owns main-window routing; `ui/merge_workspace.py` owns the workbench.
- Main toolbar Open/Save/Save as/Undo/Redo route to the active workbench. PDF shortcuts and editing controls are unavailable in Merge. Text fields retain ordinary text-edit Undo. The workbench uses the application theme and has a compact Files / Preview & pages layout below 1,000 logical pixels.
- Open-PDF snapshot capture uses the existing global engine lock. PDF mode content is temporarily disabled while capturing; mode switching remains available. Native save/insert/render calls cannot be interrupted mid-call. Snapshot exit waits for capture to finish. Disconnected network reads remain subject to OS timeouts; no claim is made that cancellation interrupts them.
- No dependencies, installer associations or Designer template-format changes were added.
- Merge also works with the Designer development flag disabled; its shortcuts, menu and exit route then use the PDF-only fallback. The Designer result action is hidden. Merging supports mixed page geometry; sending an output to Designer retains that service's existing uniform-geometry restriction.

## Targeted verification

- Related Merge, PDF tab and Designer handoff regression run: **72 passed**. Includes existing 18,000-path list tests, safe output staging/cancellation, metadata sanitization, mixed tabs, mode switching and Designer provenance.
- After final workbench refinements, new core/workbench suite at **200% scaling: 21 passed**. Additional old-core compatibility and cancel checks passed in the earlier 23-case scaled run.
- Final snapshot/Designer and Save-close checks after capture-control locking: **2 passed**.
- PDF-only build with Designer flag disabled: **1 passed**.
- Actual 20-source selected-page merge: 60 output pages in correct order, matching page provenance, original file hashes unchanged.
- Actual 200-source background merge: 200 output pages in natural order; **11.67ms** measured synchronous add and **18 GUI timer callbacks** during generation in the targeted test.
- Isolated light/dark screenshots inspected at 1280×820 and 960×640. Final narrow result view retained **170px** preview height. Preview numerals/header labels and selected-row contrast were corrected after visual inspection.
- Ruff and `git diff --check` passed. Complete regression, packaging and installer smoke testing remain deferred at the user's request.

### Performance record

Same machine, 200 local synthetic one-page PDFs, five warm-cache samples, normal output settings:

| Measurement | Previous checkpoint | New engine |
|---|---:|---:|
| Median merge time | 0.2085s | 0.2446s |
| Synchronous GUI add, final visual benchmark | — | 15.05ms |
| Fresh-process working set before/after merge | — | 45.08 / 62.93MB |
| Fresh-process peak working set | — | 62.93MB |

The new median is about 17% slower (36ms on this fixture), reflecting source/output protection and page provenance work. Redundant source opens were removed after the first comparison showed a larger regression. This is not a speed improvement claim, a cold-cache benchmark, or a memory/throughput guarantee for image-heavy, extremely long or network PDFs. Raw local artifacts are under ignored `build/merge-workbench-qa/`.

## Deferred capabilities

Duplex start/blank backs, interleaved merging, generated source bookmarks, cross-file Deep Search handoff and multiple simultaneous Merge work tabs remain outside this update. Large real-world/network fixtures and the full Windows release gates are still needed before public release.
