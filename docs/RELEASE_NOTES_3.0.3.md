# PDFDocuEdit Pro v3.0.3

Windows x64 — PDF Editing & Print Production Suite.

## New production tools

- **Flatten PDF:** analyse selected pages, flatten supported visible annotations and AcroForm appearances into page content, validate and save a new copy. Searchable text is retained unless rasterisation is explicitly chosen.
- **PDF Repair / Production Normalise:** structural rewrite, explicit normalisation options, optional before/after Production Preflight, and CSV/JSON audit reports. Maximum Compatibility is a separate rasterisation option requiring confirmation.
- Both tools are available from **Tools** and the PDF Workspace left sidebar's **Utilities**. Batch processing isolates failures per file and preserves successful outputs. Visual Workflow v6 includes corresponding cleanup nodes; checks retain temporary results, and production still requires review.
- **Shared variables:** one headless parser/resolver powers production, batch and workflow output names, with resolved previews, missing-value errors and Windows filename sanitisation. Existing `{{WorkflowSeq}}` aliases remain supported.

## Editing and stability

- Newly inserted **Add Image / Signature Image** objects can be moved, resized or edited numerically in mm, with aspect-ratio control, deletion and Undo/Redo. Saved PDFs retain editable placement information. A signature image is not a cryptographic signature.
- **Generic Barcode:** directly edit segment names, lengths and sources; detailed segment settings select fields, fixed values and sequences. Invalid lengths are explained before applying.
- **Inserter I25:** Group represents the envelope and stays constant within that envelope; Sheet is the job-wide physical-sheet sequence and does not reset between envelopes. Both start at `00` and wrap at `99`. Simplex/Duplex is explicitly selectable without requiring Print Media. Existing saved profiles are not silently changed; review/apply the current preset when updating older projects.
- **Duplex text sequences:** when Media is disabled, inserted blank backs still count in per-page sequence offsets. Preview, production and job logs agree. Previously generated affected PDFs must be regenerated.
- **Search lifecycle:** cancelled searches remain owned until they finish; only the latest queued search starts, and stale callbacks cannot replace current results.
- **Overlay loading and Undo/Redo:** clamp preview envelope/page indices before applying smaller plans; invalid drafts show validation messages instead of escaping Qt callbacks.
- **Keyboard shortcuts:** Windows Redo aliases, Designer project switching, text-entry protection and actual shortcut tooltips are consistent across modes.
- **Splash:** the application version is drawn automatically; changing the release version no longer requires editing the artwork.

## Printing

- One isolated renderer retains an open print document and renders pages incrementally. Printing no longer reopens the full PDF per page or holds the editor's global render lock during rasterisation.
- During printing, PDF scrolling, zooming and tab switching remain available; mutation, close and conflicting commands are locked.
- Accepted **Printer Preferences** are retained in the actual batch QPrinter. **Printer settings** uses the accepted custom page layout; later manual changes apply to the batch. Cancelling preferences keeps the previous selection. Driver-specific choices are session-only and must be reconfirmed after changing printer/reopening the dialog.
- Cancellation cleans up the private renderer and files. Pages already sent to the spooler may still print.

## Compatibility and limits

- Existing .pdcx, Overlay and barcode formats remain unchanged. Workflow v1–v5 remain readable; new PDF cleanup flows use v6 and cannot be opened by the older v3.0.2 installation. Older flows save upgraded copies.
- Repair does not promise to recover every malformed PDF. Unsupported XFA/appearance data blocks the affected operation. Hidden/invisible annotations may remain interactive and are reported. Non-raster transparency flattening is not provided; unverified properties are labelled Not checked.
- Signed PDFs require explicit acknowledgement that the new copy loses the original signature validity. Encryption is handled explicitly; rasterisation does not automatically OCR and loses original text/vector/interactive structure.
- Variable namespaces/transforms currently target naming; Designer text and barcode formats retain their existing supported syntax.
- Software checks do not establish physical printer tray/duplex/finishing or inserter acceptance. Validate the output with the actual devices and their configured profiles.

## Downloads

Install **Setup-Windows-x64.exe**, or extract **Managed-Portable-Windows-x64.zip** and open **Launcher.exe**. Existing managed installations use **Help → Check for Updates**.

The release includes the signed Update ZIP, `update.json`, `update.sig` and SHA-256 files. No macOS installer is supplied for this release.

Release evidence: [v3.0.3 validation](RELEASE_VALIDATION_3.0.3.md). Publication status, exact payload commit and final checks are recorded in the GitHub release.
