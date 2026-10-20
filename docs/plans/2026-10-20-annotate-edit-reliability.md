# Annotate & Edit reliability

Approved in conversation, 2026-10-20. Baseline: `1d48fa9e396ae3b23ec198e5c1ce9c11e42989d4` on the existing D drive development line. Do not switch branches, merge, push, publish, or change the version. Preserve the untracked owner profile.

## Execution

1. **P0 open/render recovery.** Reproduce a failed open/render followed by other PDFs in the same process. Retain reader ownership; balance pauses and refill after resume. Make bootstrap reversible without losing the previous engine, draft or history. Distinguish stale/cancelled/failed renders, retry once automatically and expose Retry/Close after persistent failure. Announce loaded only after visible pixels. Log identities and numeric lifecycle counters, never document contents or exception payloads.
2. **Rotation geometry.** Calculate stamp dimensions and appearance in visible coordinates before the existing single derotation. Preview must use intrinsic stamp/image proportions. Check image/signature/FreeText and selection resizing without undoing existing bounds fixes.
3. **Persistent editable watermarks.** Use owned ordinary PDF content with versioned metadata and embedded resources. Support nine anchors, mm offsets, uniform size, arbitrary angle, opacity, page ranges, worker preview, edit/move/resize/delete after save/reopen. Default centre, 25% opacity, text 64 pt / 45 degrees, image 0 degrees. Per-page fitting, atomic undo, copy-on-write, strict ownership/transform validation. Do not infer ownership of external or legacy watermarks.
4. **Regression and review.** Test 0/90/180/270 degrees, CropBox, asymmetric pixels, zoom/DPI, undo/redo, save/reopen, discard/reopen, split view, injected failures and cross-document recovery. Run targeted tests, full regression, Ruff and practical Windows build checks. Report synthetic/engine/GUI/packaged validation separately; original incident is not considered uniquely diagnosed without natural reproduction.

## Boundaries

Keep existing PDF engine, mutation/authorization rules, reader leases and source preservation. Never force-unlock the global PDF lock, kill readers, clear the global pool, or close a leased document. Newly added watermarks remain ordinary printable PDF content, including when annotations are hidden. External modifications that invalidate owned content must block destructive editing while leaving PDF display intact.
