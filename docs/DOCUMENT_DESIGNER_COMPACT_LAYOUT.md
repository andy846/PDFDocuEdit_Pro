# Document Designer compact layout — 2026-10-02

## User-facing changes

- Merge the project and insert toolbars into one compact row. Keep New/Open/Save,
  Undo/Redo, element insertion, Data import, font size, zoom, Fit page and Generate PDF
  reachable. Detailed commands and keyboard shortcuts remain in their existing menus.
- Remove the repeated workspace title and description below the main toolbar.
  The native window title continues to identify the Designer/project.
- Combine template page navigation, page actions and preview state into one canvas header.
  Record navigation appears here only in Preview, with direct ordinal entry and
  first/previous/next/last controls. Data, Design and Production use that space for content.
- Replace the separate multiline message/footer/navigation/progress rows with one status bar.
  Progress and Cancel appear during import/production. Selection and page metadata remain
  visible; page dimensions are available as a tooltip.
- Long status messages are drawn as one elided line while retaining their full text.
  Hover for the full tooltip, double-click or focus and press Enter/Space for details,
  or use the context menu to show/copy the complete message. Coordinate updates cannot
  conceal a nonempty Designer status message.
- Use icons and scoped padding instead of reducing the application text size.
  Narrow windows retain the existing tabbed Data fields/Layers/Properties inspector.
  Refresh and page action icons follow theme changes.

## Measured layout change

Same machine, offscreen Qt, 960×640 logical window, QT_SCALE_FACTOR=2,
registered bundled Noto Sans/CJK fonts, Noto Sans 9 pt, real application palette/styles.
Baseline modules loaded from commit 0bf1304 in a separate process, isolated QSettings.
Dark and light themes produced the same geometry.

| Measurement (logical px) | Before | After |
| --- | ---: | ---: |
| Toolbar rows | 2 | 1 |
| Toolbar height per row | 47 | 37 |
| Canvas viewport height | 258 | 486 |
| Canvas viewport width | 632 | 636 |
| Central working area height | 344 | 518 |
| Status bar height | 22 | 22 |

The canvas gains 228 logical vertical pixels (+88.4%) at this size. The existing status
bar itself was already small; the extra message/navigation/footer rows were the main
bottom-space cost. This is a viewport comparison, not a rendering-speed benchmark.
Raw measurements/screenshots: build/qa-compact-layout/{before,after}.

## Architecture and compatibility

Changes are isolated to composition/designer. compact_chrome.py contains the scoped
styles and full-message label. chrome.py owns the toolbar, pages.py the page header,
workspace.py the layout/mode transitions, and usability.py the existing inspector adaptation.
No template/schema changes, migrations, new dependencies, public version change or engine
changes are required. Original primary fonts, automatic glyph fallback, imported data,
sequences, rules and production job/report contracts are preserved.

## Verification

- tests/composition/test_compact_layout.py verifies both themes at 960×640 and 760×580:
  useful canvas space, reachable controls, 50,000-record ordinal navigation, no template
  mutation on mode changes, full multiline messages, keyboard details and busy-only progress.
- All 255 Composition tests pass at 200% scaling (build/qa-compact-layout.xml).
- scripts/composition_layout_qa.py is called by the existing native/frozen smoke suite;
  it captures both themes and the narrow Preview layout using actual fonts/styles.
- All 1,088 project tests pass (873.45 seconds), with no skipped, disabled or failing tests.
  Full Ruff check passes. Windows frozen smoke passes at 200%, including the layout checks
  and existing Excel/sequence/rules/barcode/font fallback/production flow.
- Final complete-project and frozen-build results are recorded in
  validation/document_designer_compact_layout_20261002.json.
- No printer/physical monitor acceptance is claimed by the offscreen verification.

## Test build and rollback

Isolated build: dist-compact-designer/PDFDocuEdit Pro/PDFDocuEdit Pro.exe.
Public application version remains 2.5.15 for this development build.
The prior auto-font build/tag remains available as a rollback:
document-designer-auto-font-dev-20261002 (0bf1304).
New checkpoint: document-designer-compact-layout-dev-20261002.
