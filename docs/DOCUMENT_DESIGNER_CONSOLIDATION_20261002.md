# Document Designer convenience and reliability update

Date: 2026-10-02 (Hong Kong)

## Changes

- The shared Properties panel can switch an existing barcode between Code 128, I25 and QR without deleting/recreating it. Content, ID, position, size, font and envelope profile remain in place. QR disables the linear readable caption; associated caption glyph repairs are cleared only on that conversion. Undo restores the original object.
- Normal Designer Layers now has a clearable search field. Its query remains through content editing and Undo/Redo; matching follows updated object text.
- PDF overlay has searchable Fields and Objects tabs. Objects includes marks on other pages and displays control-barcode labels and page scopes in tooltips. Selecting an off-page object navigates to an applicable page. Multi-selection uses a common applicable page and explains incompatible page scopes.
- Selected overlay barcodes show the current exact payload, character count and profile name directly in the inspector. The text can be selected/copied.
- Barcode payload editor adds Move up/Move down with boundary states. Literal tokens disable numeric width controls and do not carry field padding into the payload.
- Profile preview shows current and first/last applicable mark samples. The dialog uses the same payload validator as rendering and disables OK for invalid samples. Source-only profiles exclude inserted blank backs in duplex jobs.
- Overlay background preview has Updating/Ready/Failed states. Errors identify a Review object link when an object ID is available; it selects the object and focuses its relevant inspector control.
- Invalid overlay drafts invalidate queued previews and clear the stale image. Save/Generate/object switching stay protected until correction or Revert. Revert schedules a new preview; stale callbacks cannot restore the previous valid image over an invalid draft.

## Architecture and compatibility

The payload checker is a Qt-free helper in composition/engine/barcodes.py. Overlay navigation/feedback stays in composition/designer/overlay_usability.py. PDF production rendering and existing source preservation retain their current implementation. No new dependency, public version change or JSON schema migration; normal templates remain version 6 and overlay projects version 1.

This update improves the existing generic payload builder. Manufacturer-specific inserter presets and protocol rules still require the user's actual specifications and samples.

## Focused validation

Per the user's instruction, validation was limited to changed interactions and shared barcode paths:

- 24 passed in 2.27s: new interaction cases, I25 cases and the two existing Code 128/QR renderer checks.
- 1 passed in 1.41s: real background overlay preview, invalid-I25 error, and Review object navigation.
- Total: 25 targeted cases passed. UI cases run with QT_QPA_PLATFORM=offscreen. Interaction-only cases avoid font inventory and background PDF generation; the final case exercises the real preview worker.
- Ruff checks on modified/new Python files passed; git diff --check passed.

Full regression, large performance runs and Windows packaging await completion of the user's modification batch. Existing packaged executables are unchanged.
