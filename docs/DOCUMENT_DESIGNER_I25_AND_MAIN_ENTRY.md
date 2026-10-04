# Document Designer: I25 and main-window entry

Date: 2026-10-02 (Hong Kong)

## I25 / Interleaved 2 of 5

- Available from Insert and the Barcode menu in Document Designer, and Insert in PDF envelope overlay.
- Uses the existing python-barcode dependency and vector PDF renderer; no new dependency.
- Content accepts variables, running sequences and existing alternative-content rules.
- Overlay content uses the existing barcode payload profile, scopes and control-marker settings.
- Payload must contain ASCII digits 0-9 and have an even length. Leading zeros remain unchanged. Odd-length data is rejected before the library can silently pad it; no checksum is appended.
- Wide/narrow ratio: 3:1. The bounding box includes ten narrow modules of white quiet zone on each side. Existing minimum-module and optional readable-text controls apply.
- Shared font preflight, font subsetting and bulk typography include I25 readable text.
- Envelope production counts and decodes I25 marks on the final PDF, matches the exact payload, and records the symbology and value in existing barcode reports.
- Templates/projects keep their existing JSON schema versions; I25 is an additive element type.

## Main-window entry

- A primary-colour Document Designer button sits on the existing top command bar and invokes the same action as Tools > Document Designer.
- It stays available with or without an open PDF, and respects the existing Composition development feature flag.
- The command bar keeps its 44px height. Below 760px the label becomes Designer, with the full accessible name and tooltip retained; direct Search and Redo icons use their existing menus/shortcuts to keep the entry within 640px.
- Optional controls use the remaining width after reserving space for the new entry.

## Focused validation

User requested targeted tests while this modification batch is in progress.

Command:

    python -m pytest tests/composition/test_i25.py tests/composition/test_designer_entry.py tests/composition/test_renderer.py::test_code128_and_qr_decode_exact_payloads tests/composition/test_renderer.py::test_barcode_size_and_payload_errors -q --tb=short

Result: 18 passed in 6.03s. Tests cover exact decoded values, leading zeros, readable text, vector output, invalid payloads, geometry limits, template/rule persistence, two-record data production, six-page envelope production/reconciliation/reporting, insert actions and the feature-gated main-window entry.

A follow-up check of the formal stylesheet found the initial narrow layout could grow from 640px to 677px. The final adjustment hides two secondary icons at that width. Only the two affected entry tests were rerun, with an added exact-width assertion: 2 passed in 1.47s. They check 640/960/1280px in native and integrated chrome.

Ruff was limited to changed Python files and passed. Full regression, large benchmarks and Windows packaging are deferred until the user confirms the modification batch is complete. The existing dist-pdf-overlay executable predates these changes and has not been replaced.
