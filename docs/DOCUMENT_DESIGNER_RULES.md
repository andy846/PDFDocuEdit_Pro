# Document Designer - conditional rules implementation note (2026-10-01)

## Architecture review

Current baseline: d21ae5c / document-designer-usability-dev-20261001. Designer is an isolated
PyQt6 window; preview and production use QProcess workers and a shared headless Renderer.
Data is an imported SQLite snapshot. Exact fonts and per-glyph repairs are preflighted by
streaming records. Production publishes only validated, reconciled output.

## This milestone

Structured ALL/ANY field conditions: exact text comparisons/contains/prefix/empty and finite
Decimal numeric comparisons. Per-object visibility plus one conditional content/image variant.
Design shows base objects; record Preview and production apply identical plans. No eval or scripts.
Fixed template pages are still always emitted, including pages with no visible objects.

Files: template/model.py (schema 4; read v1-v3), engine/rules.py (bounded compiled plans),
engine/renderer.py and subsets.py (shared selected branch and streamed preflight),
template/serializer.py (both image assets), production/model.py and generator.py (rule summary,
record errors and asset fingerprints), designer/rules_dialog.py and rule_controls.py (isolated UI),
minimal properties/chrome/workspace hooks, worker preview metadata, focused tests and smoke.
No editor rewrite, new dependency, public version change or output splitting in this milestone.

All mapped references and declared resources must exist. Only displayed text is glyph-checked.
Invalid numeric data blocks the job before composition with record/object/field context.
Rule summary distinguishes preflight completion from published output; no per-record data in logs.

Gates: headless rule/schema/security/selected-text/asset tests; real Designer interactions and
Undo/save/preview; frozen and installed 100-record multi-page workflow; full regression and
repeatable no-rule performance comparison. Keep the preceding executable and Git tag for rollback.

## Using object rules

1. Import CSV/TXT and finish field mapping.
2. In **Design**, select one object. Choose **Rules > Edit object rules...** (Ctrl+Shift+R),
   the canvas context menu, or **Properties > Object rules > Edit rules...**.
3. Enable **Visible when** to control visibility. Select a mapped Field, comparison,
   **Text** or **Number**, and a value. Choose **All conditions** or **Any condition**.
   Up to 20 comparisons per group are supported. Unchecked means always visible.
4. For text, Code 128, QR or images, optionally enable **Use alternative content when**.
   Enter alternative static/mixed/variable text ({{Account_No}}) or choose a static image.
   There is one alternative per object; it shares the object's geometry, font and explicit
   per-glyph repairs. Lines/boxes support visibility only.
5. **Check imported sample** checks the cached sample rows, which can have truncated values.
   Use **Preview** for the full selected record. **Design** always shows the normal objects
   and field placeholders so hidden objects remain editable.
6. Apply with **OK**; **Cancel** preserves existing rules. Undo/Redo, page duplication and
   copy/paste retain rules. Clear rules restores always-visible normal content.
7. Save as a new .pdcx, preview different records, then generate. The summary, control.csv and
   job.json include configured objects, checked records, hidden/alternative occurrences
   and whether the complete input was checked.

Example: Visible when **All**: Scheme_Code / Equals / Text / GS; Balance / Greater than /
Number / 10000. A separate object can use alternative text "GS Account: {{Account_No}}"
when Scheme_Code equals GS.

### Exact behavior and limits

- Text is case-sensitive and preserves spaces and leading zeros. Is empty means exactly "".
- Number uses finite Decimal values with a dot separator. Currency symbols, commas,
  exponent notation and blank numeric data are rejected. Correct the source/mapping and
  reimport; no implicit conversion or user scripts run.
- Every enabled comparison in a group is validated, even when another comparison determines
  the All/Any result. Visibility is checked first; alternatives are evaluated only for visible
  objects. Missing mapped references are always errors, including references in an inactive branch.
- All declared fonts and base/alternative image files must exist. Hidden text is not glyph-checked;
  only the selected text branch is checked. No automatic font replacement is introduced.
- All fixed template pages are produced for every record, even if all objects on a page are hidden.
  Rules do not remove pages, flow text, insert pages or split files.
- Numeric rule errors identify the imported record, template page, object and field before
  composition starts. Failed/cancelled jobs do not publish a production PDF.
- Rule totals describe the preflight scan. On cancellation/failure they may be partial, including
  objects already checked within the failing record; records_checked counts whole records and
  complete is false. A complete scan alone does not mean output was published.
- Preview uses the same rule selection as production; jobs still validate barcode sizes,
  text overflow and exact glyph rendering before publication.

### Project compatibility and rollback

Schema 4 reads versions 1-3 and preserves original geometry, fonts and per-glyph repairs.
Saving writes schema 4. Earlier executables cannot open newly saved schema-4 projects.
Use **Save as** and retain the preceding project/asset folder if you need rollback.

Public application version remains 2.5.15 for this development delivery. No new dependency,
editor rewrite, public release, output splitting or automatic processing is included.

## Validation - rules development milestone

Code checkpoint: 889b4e6. The focused Composition run passed 156 tests; the final 21
rule/usability interaction checks passed after the mode/button synchronization improvement.
Existing schema-version assertions now use TEMPLATE_VERSION; legacy v1/v2/v3 fixtures remain
explicit. No existing test was disabled or removed.

Native 200%, frozen 200% and QA-installed 100% workflows passed, each composing 100 records
into 200 pages. Checks include conditional visibility, normal/alternative text and static
images, rule save/reopen, summary reconciliation, exact Windows font face, CJK, explicit
per-glyph repairs, QR/Code 128 decoding, and the existing editor opening a PDF.
Screenshots were inspected using offscreen Qt. This does not certify physical printer output.
The isolated QA installation was removed; no PDF file handler was registered.

### Performance (five trials per fixture/size)

| Fixture (2 pages/record) | Records | Median generation | Composer peak (median) | Assembler peak (median) |
| --- | ---: | ---: | ---: | ---: |
| Plain (no rules) | 1,000 | 2.98 s | 78.7 MiB | 27.5 MiB |
| Plain (no rules) | 10,000 | 27.00 s | 101.0 MiB | 191.5 MiB |
| Conditional text/visibility | 1,000 | 4.66 s | 78.9 MiB | 30.4 MiB |
| Conditional text/visibility | 10,000 | 41.11 s | 101.7 MiB | 223.0 MiB |

The no-rule generation medians are +9.93% / +4.04% against the previous two-page fixture
baseline (2.710956 / 25.954071 s). Conditional fixtures contain an extra object on each page,
so their times are not an isolated estimate of predicate overhead. All five 10,000-record
conditional trials reconciled 20,000 pages, 10,000 hidden occurrences and 10,000 alternatives.

These are synthetic local fixed-page results. Cold/warm caches and host activity were not
controlled; focused GUI checks overlapped parts of the series. They are observations, not a
strict performance guarantee. Composition is chunked; qpdf still scales memory with output
objects. Raw samples: validation/document_designer_rules_benchmark_20261001.json.

### Local test delivery

- Executable: dist-rules/PDFDocuEdit Pro/PDFDocuEdit Pro.exe.
- Portable: release/PDFDocuEdit-Pro-v2.5.15-Document-Designer-Dev-Rules-Portable-Windows-x64.zip
  and .zip.sha256.
- Synthetic example: release/Document-Designer-Rules-Demo/Conditional-statement.pdcx, source.csv,
  copied static assets and README.txt.
- Previous rollback: document-designer-usability-dev-20261001. Retain older templates as well as
  the older executable. This milestone saves schema 4.

Final full Windows regression on checkpoint 889b4e6: **989 passed, 0 failures/errors/skips**
(797.17 s), including all **156 Composition tests** / 55 new rule cases. Full evidence:
validation/document_designer_rules_20261001.json. Final Git tag: document-designer-rules-dev-20261001.
