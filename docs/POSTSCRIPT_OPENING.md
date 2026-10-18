# Verified PostScript opening previews

## Behavior

Editor PS/EPS opening now follows stable source snapshot/hash, cache lookup,
conversion on a miss, PDF validation, independent working-copy preparation and
first-page delivery. Ordinary PDF opening remains on the existing path.

The local preview cache persists across application restarts. Defaults are
2 GiB total PDF storage including staged previews, 512 MiB per entry, and seven
days since last use. Oversize previews open normally without being cached.
Preferences exposes enable/disable and asynchronous Clear PS previews actions.
Cached previews contain document content and are not release assets.

Keys bind the complete source SHA256, converter executable/version and Windows
DLL fingerprint, interpretation profile and cache schema. Filename, file length
and mtime are not sufficient. Hits verify the derived PDF digest and page tree.
Editor and production-validation profiles are distinguished. Editor edits never
write to a cache entry or overwrite the original PS; the existing independent
PDF working copy and Save As behavior remain in use.

A source is copied and hashed in one background pass. Handle and path identity,
size and timestamps are rechecked before using that snapshot. Windows handle
ctime and path ctime are compared within their own timestamp families because
this runtime exposes different values for them.

## Integration and safety

- `core/postscript_cache.py`: Qt-free optional cache, source snapshots, bounded
  pending previews, SQLite cross-process exclusion, content checks and OS-held
  pending-file leases. Clear increments an epoch, prevents in-flight work from
  repopulating cleared content, removes abandoned owned files and defers active
  previews until their worker finishes. Disable also reaches existing workers.
- `core/postscript_open.py`: background conversion with one-second heartbeats,
  real process cancellation/reaping, atomic output replacement and phase timings.
  Editor uses a 60-minute conversion limit; other callers retain 300 seconds.
  Unknown page progress stays indeterminate. Raw PS process output is bounded in
  private temporary storage and removed, never sent to application diagnostics.
- `core/tools.py`: preserves the two positional conversion arguments and adds
  optional progress, cancellation, timeout, profile and trace parameters.
- `core/viewer.py`: routes queued PS opens through the service, retains task
  ownership until completion and suppresses cancelled results. Trace starts
  before conversion, not only after a PDF exists.
- `core/pdf_io.py`: optional cancellation/progress during existing page-tree
  validation. Editor cache/native validation uses the existing document lock;
  standalone production workers remain independent and the cache imports no Qt.
- `core/cancellation.py`: shared exception, re-exported by `core/tasks.py` for
  existing callers without changing cooperative cancellation behavior.
- Composition private stdin carries resolved cache configuration, without adding
  cache fields to project files, production jobs, approval receipts or request
  JSON. A scoped preview sink retains the PDF actually interpreted from PS.
- The PS exporter stages this already-validated result; the journal publication
  hook activates matching final PS hashes only after successful publication.
  Template, Overlay, bounded packages and Visual Workflow split output share
  this path. Failed or superseded attempts do not become reusable entries.
- Optional cache, converter-fingerprint and cache-cleanup failures do not change
  a successful production result or prevent an otherwise valid conversion.

No conversion quality preset, downsampling, rasterization, font substitution,
production authorization, print selection or output reconciliation rule changed.
A cached interpretation is not printer/RIP acceptance evidence. A same-name PDF
is never substituted for PS. New third-party dependencies were not added.

## Evidence — Windows, 2026-10-18

For the supplied 56 MB, 2,388-page PS, one full diagnostic run measured:

| Stage | Time |
| --- | ---: |
| Cold preparation including complete PS conversion | 253.762 s |
| Warm preparation with verified cache | 0.272 s |
| Fresh offscreen Editor, cached request to first-page delivery | 478.445 ms |
| Fresh offscreen Editor, cached request to next interactive turn | 478.962 ms |

Cold and warm first-page render pixel SHA256 values matched; the original PS
SHA256 was unchanged. Engine timings are not compositor timings. The cold/warm
run overlapped other regression activity and is not a controlled multi-run
throughput benchmark or a guaranteed speedup for other PS files.

A matched ten-page comparison with image deduplication disabled improved from
20.979 s to 20.160 s and increased bytes from 383,601 to 395,291. All ten pages
had identical rendered pixels at 150 DPI, dimensions and extracted text. The
small observed benefit did not justify changing that default.

An external PS without a matching cache still needs full first interpretation.
Newly generated PS can reuse its existing validation interpretation on first
open. Older outputs require one successful conversion to seed the cache.

Automated evidence is retained locally under
`build/probes/ps-open-implementation/`; it is not committed. Core tests cover
source/cache identity, corruption, cancellation, expiry, capacity, leases,
clear/disable races and optional failures. Actual Ghostscript tests cover
Template, Overlay, both split routes and private worker stdin handoff. UI tests
cover light/dark, narrow windows, cancelled opens and destroyed Preferences.

Final selected regression: **333 passed, 0 failed, 0 errors, 0 skipped** across 20 modules. Independent review found three optional-cache boundary issues; all were reproduced and fixed, with regressions for converter identity failure, clear during conversion and abandoned staged content.
The 9 UI cases also pass separately at 200% scaling. Prepared-font light/dark
Preferences screenshots were inspected at 960x640 logical pixels and DPR 2.
macOS native appearance/cancellation and owner interactive checks: Not Tested.
The complete repository suite and real printer/RIP testing were not run.

## Maintenance

Increment the cache schema/profile revision when interpretation semantics change.
Keep the production and Editor profiles explicit. Cache failure handling must
remain separate from production success or failure. Do not remove the final
source/content checks or native-reader protection to improve benchmark numbers.
No public version, branch, project-format or release change is part of this work.
