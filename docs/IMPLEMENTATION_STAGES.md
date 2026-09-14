# Stability, shortcuts, AcroForm and comparison

## Stage 1: ownership, diagnostics and deployment

Transaction boundaries deliberately catch BaseException to restore the document/history before propagating interruption. Qt worker boundaries separately handle ordinary errors and KeyboardInterrupt/SystemExit: terminal signals release pending work; SystemExit is queued to the GUI's normal close handling, preserving unsaved-document prompts. KeyboardInterrupt cancels the affected task. Fallback diagnostics retain exception types and frame locations, excluding exception messages, source snippets and frame locals.

Managed startup contract: a versioned editor is identified by its `.managed-update` marker and root `state.json`. Direct launches delegate to the fixed `Launcher.exe`, preserving arguments; incomplete managed installations report a repair message instead of starting with a different settings directory. Launcher creates the root/token environment and `launch.json`; the editor validates it, locks its session and completes the readiness handshake. An unrelated `versions` folder is not sufficient evidence of a managed install.

Dependencies intentionally retained:

| Package | Runtime reason |
| --- | --- |
| pdf2docx | PDF → Word converter |
| python-docx, fonttools, fire | Declared dependencies of pdf2docx |
| termcolor | Declared dependency of fire |
| lxml | Required by python-docx; also used by XML-related integrations |
| openpyxl, et-xmlfile | Excel outputs and their XML writer |
| cryptography | Signed updater verification |

The docx PyInstaller imports remain required for packaged conversion. Existing versioned release notes are historical documents, not inconsistent version constants.


## Shortcut editing

Preferences → Keyboard shortcuts lists application command IDs, including Organizer,
form and comparison commands. Conflicting sequences and multi-stroke prefixes are
rejected in overlapping scopes. Clear and Restore use the existing settings format.
Text editing retains its own keyboard behavior. Context-menu hints use current
bindings; open comparison windows refresh after Preferences is applied.

## Existing AcroForm filling

Choose Utilities → Fill PDF form. The field list shows type, page, value, and flags.
Select a field in the list or click its region in the preview. Edit a staged value,
choose Update preview, then Apply. Calculations and values share one document Undo
step. Closing the editor discards staged values. Save preserves editable widgets.

Supported calculations are SUM, AVG, PRD, MIN and MAX through AFSimple_Calculate,
plus event.value expressions containing numeric constants,
this.getField("name").value references and +, -, *, / operators.
No JavaScript runtime or Python eval is used. Cycles, missing references and invalid
arithmetic stop Apply. Unsupported scripts remain in the PDF and require an explicit
confirmation; the tool does not execute validation/formatting scripts.

Checkbox/radio choices use the actual PDF appearance states. Choice fields preserve
export values separately from labels. Multiple widgets of a logical field are
updated together. Unicode appearances embed a CJK font while retaining editable
values. Signature images and handwriting change only an unsigned field's appearance;
they do not create or validate a cryptographic signature. XFA is rejected.

## PDF comparison

Choose Utilities → Compare PDFs. A is the current unsaved document snapshot.
B can be another open document or a password-protected external PDF. Compare / Refresh
creates an independent result with ordered page pairs and Added, Deleted, Modified,
or Same classification. Use the pair controls to correct heuristic matching; moved
pages appear as deletion/insertion. Pairing cannot cross an existing pair.

Visual mode preserves size and rotation and highlights grouped differences.
Text mode compares Latin words and CJK characters with their page positions.
A page without selectable text is compared visually without automatic OCR.
Results are only displayed in the app. Neither source is modified and no report is written.
Source revision changes mark existing results out of date. A confirmed external snapshot
survives later file changes; refreshing reopens the file and requests its password again.

Comparison workers open their own snapshot documents and check cancellation at page
and alignment boundaries. Page rendering uses the existing on-demand bounded cache.
Alignment uses exact anchors, with bounded matching for changed runs; very large
unmatched runs fall back to positional pairing and can be adjusted manually.
Visual analysis uses 96 dpi, reduced for unusually large paper to cap the longest
edge at 2400 pixels. This is a review aid, not a guarantee that every tiny raster
difference will be detected.

## Local validation

New regression suites: test_stability_improvements, test_scoped_shortcuts,
test_forms, and test_comparison. scripts/features_smoke.py drives generated
documents through the native UI, Apply/Undo/Redo and asynchronous comparison; it can
also be frozen with the application spec. All QA output is under ignored build/.

The clean build/validation-env is installed from requirements-base.txt.
Dependency validation includes pip check, PDF-to-Word conversion/reopen, and Excel
merge/reopen. No GitHub release or repository-visibility change is part of this work.
