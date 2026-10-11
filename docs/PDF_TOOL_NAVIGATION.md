# PDF Workspace tool navigation

## Finding tools

The left sidebar contains Favourites and six task categories:

| Category | Tools |
| --- | --- |
| Search & Inspect | Search document, Deep search, Find and open PDF, Document information, Inspect text font, Smart Detection, Compare PDFs |
| Pages & Documents | Insert, Delete, Extract, Order, Advanced Page Organizer, Split, Rotate, Merge |
| Annotate & Edit | Text markup, notes, freehand drawing, shapes, text boxes/callouts, images, signature images, stamps, watermark, Fill PDF form, Redact |
| Convert | OCR and existing PDF/Office/Text/PostScript conversion tools |
| Production & Data | PDF Production Tools, PDF overlay, Batch print, Compress, reports, text extraction, CSV/Excel merge, barcode tools |
| Security | Encrypt PDF, Remove security |

All 51 existing tool identities and handlers are retained. A signature image is still an image appearance, not a cryptographic signature.

## Favourites

The initial favourites are Search document, Deep search, Merge PDFs, Extract pages and PDF Production Tools.
Use **Favourites → Edit** to add/remove tools and move them up/down. Up to eight can be pinned.
Right-click a tool in an expanded category to add/remove it. When the list is full, use Edit to remove a tool first.
Confirm with OK; Cancel leaves the saved list unchanged. An empty favourites list is supported.
Unavailable tools can be pinned but retain the same disabled state and explanation as their category entry.

## Compact navigation

Use the collapse button or the existing Toggle Tools Panel shortcut (**Ctrl+\** by default).
The 52-logical-pixel rail contains Search, favourite tools and category icons.
Click a category to open its searchable full-name list; hover does not open it.
Use arrows to select an available result and Enter/Space to activate. Esc or an outside click closes the popup.
A long popup or short sidebar can scroll. The popup is bounded to the current screen.
The expanded sidebar remains 272 logical pixels wide. Long labels are elided and retain full tooltips/accessibility labels.

## Search and status

Search matches names, descriptions, categories, old category aliases and current customized shortcut hints.
Multiple words must all match. Chinese aliases are provided for common search, merge, extraction, font and production tools.
Searching temporarily reveals matching groups; clearing the search restores each group's expanded state.
A saved expanded search does not hide favourites in the compact rail.
No match displays a clear message. Unavailable tools explain whether a PDF or a platform dependency is needed.
Canvas editing modes remain visibly selected across matching sidebar views. Dialog actions do not retain a misleading selected state.

## State and compatibility

Favourite order and category expansion use the existing Qt settings backend under `sidebar/v2/`.
Old section preferences remain intact; the new categories start collapsed on first use.
Unknown/duplicate saved favourite IDs are ignored. No project or PDF format migration is introduced.
Responsive collapse for a narrow document-details view does not overwrite the user's saved preference.
When the window becomes wide enough again it restores the expanded panel; explicit user collapse remains respected.
Tool tabs and Designer mode continue to use existing routing, task ownership and shortcut protection.

## Targeted validation

- Favourite persistence/order/empty lists, unavailable tools, search aliases and customized shortcuts.
- Category completeness, keyboard routing, popup bounds, repeated opening, elision, theme refresh and animation preference.
- Narrow windows, scroll reachability, fixed dialog actions, responsive preference restoration and PDF page/zoom/revision preservation.
- Windows native 200% UI captures in dark/light themes; native navigation tests passed. macOS native visual acceptance remains for the Mac test environment.
- Existing Merge, shortcut, source/tool-tab and Production Tools routes are checked separately.
- 76 distinct targeted cases passed: 17 navigation, 4 category/icon compatibility, 21 UI/shortcut, 24 Merge, 3 Production Tools routing, 6 small-window and 1 legacy search case. The 17 navigation cases also passed with native Windows widgets at the system 200% display scale.

One initial combined Qt test process terminated in a native access violation during Designer creation.
The affected Merge and shortcut groups passed when rerun in separate processes; this is not recorded as a complete regression pass.
This development update does not change the public version, trigger packaging, or publish a GitHub release.
