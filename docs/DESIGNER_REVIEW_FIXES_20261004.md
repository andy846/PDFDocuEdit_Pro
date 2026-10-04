# Document Designer review fixes — 2026-10-04

## Scope

Fix the confirmed findings from the Document Designer review. Preserve existing template formats, public version, dependencies and production backends. Full regression and Windows packaging remain deferred until the user completes the current batch of changes.

## Functional corrections

1. **Overlay source reinspection / regrouping** now starts from a copy of the current project and replaces its source and grouping. Project name, media rules, external fields and objects remain intact. Source-link and detection acceptance retain their existing source identity checks. An explicit simplex/duplex change updates enabled media settings too. Incompatible retained media rules block generation and remain editable. Undo restores the previous project.
2. **Add paper rule** uses the actual template page ID or a valid page role. It offers unassigned pages/roles, restores deleted rules and avoids creating duplicate keys. Template page labels remain human readable; their saved identity stays stable.
3. **Assign by changes** retain separate in-dialog drafts, including incomplete rows. Initial page-number/template conversion uses actual template pages. Loading another profile clears the old profile's draft cache. Only the selected mode is saved to the project; template format is unchanged.
4. **Duplicate / Paste rotated objects** uses the shared rotation-aware bounds helper after applying the copy offset. Copies are translated inside the target page where possible. Oversized copies report an error without partially committing the operation. Text, font, angle and other properties are retained; the operation remains one Undo step.

## UI corrections

- Properties places X/Y and width/height in two columns, followed by angle.
- Font size follows Family and Style. Advanced font-file and glyph-repair controls are in a collapsible section; font status stays visible.
- Expanding advanced settings preserves selection and unapplied batch edits.
- Inspector layout invalidation visits its own public layouts, rather than Qt's internal combo/spinbox children. Selection changes refresh layout immediately.
- Workflow Save stays visible in Build, Review and Run and uses the existing background save handler and Ctrl+S routing.

## Targeted verification

| Check | Result |
| --- | --- |
| New regressions plus Media UI, compact layout, batch editing, usability, canvas continuity and Workflow home | 86 passed |
| Active-mode shortcuts, save/reopen, integrated inspector and narrow theme controls | 8 passed; 27 unrelated cases deselected |
| After final inspector refresh: new regressions, batch editing and canvas continuity | 50 passed (repeat verification of affected cases) |
| After extending inspector checks to all five geometry controls | 4 passed; 31 unrelated cases deselected |
| Ruff on all changed Python files | Passed |
| Git whitespace check | Passed |

The new tests include an actual overlay generation after regrouping: six PDF pages, preserved stock counts and an emitted JDF ticket. They also cover invalid retained stock assignments blocking generation, project save/reopen with external fields, simplex/duplex Undo, fourth-page and deleted-page assignment, role drafts, profile replacement, page-choice cancellation, rotated Paste/Duplicate and asynchronous Workflow Save.

UI modules now share a session-owned QApplication fixture. Earlier combined review runs had terminated while Qt applications were destroyed/recreated between modules; the targeted combined run now completes normally. This addresses the test lifecycle and does not establish a previously observed production crash as fixed.

## Visual inspection

Independent offscreen Qt probes use isolated settings and bundled fonts. Screenshots cover standalone Designer at 960×640 and 760×580, dark/light themes and 100%/200% scaling, plus the integrated Template, Preview, Overlay, Workflow and empty Designer screens. Inspector horizontal scrolling remains zero in the integrated targeted tests, and all geometry/font/content controls can be scrolled fully into view.

Artifacts are in:

`C:\Users\andy8\.codex\visualizations\2026\09\26\01a0deec-4c31-7983-9103-b1580e48c4e2\designer-fixes-20261004`

Original review artifacts remain in the separate `designer-review-20261004` directory. The user's running application and unsaved projects were not closed or changed. Offscreen inspection is not a substitute for the user's interactive Windows acceptance test.
