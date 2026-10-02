# Document Designer dual workspace modes

Date: 2026-10-02 (Hong Kong)

## Operation

- The main toolbar now contains **PDF Workspace | Document Designer**. Startup remains in PDF Workspace. Below 900 logical pixels the labels shorten to PDF | Designer to leave room for window controls and menus.
- Selecting a mode slides its highlight and crossfades the workspace for 200 ms. The existing animation preference also controls these transitions. Rapid selections cancel the previous transition and display the last selected mode.
- Designer is created on first use. Template projects and PDF envelope overlays are embedded in the same main window, with their own persistent project tabs. Their window title bars and menu bars are hidden; the main menu and overflow menu display the active project's commands.
- New/Open creates a project tab. Opening an already open project path focuses its existing tab. Windows path identity ignores case and resolves relative paths; Save As rejects another open tab's target.
- Workspace > New project (Ctrl+N) creates a template when a template is active, or an overlay when an overlay is active. Workspace also provides an explicit New PDF envelope overlay entry. Template File/toolbar > New creates a new template tab. Overlay File/toolbar > New source creates another overlay when the current project already has a PDF. Reinspect deliberately updates the existing overlay source.
- Ctrl+O opens a Designer project in Designer mode. Ctrl+S, Ctrl+Z and the other editing shortcuts target the active project; inactive project and PDF shortcuts are removed temporarily, then restored on return. Text editors retain native text Undo and editing behavior. The command palette and shortcut reference follow the active mode.
- Switching modes or tabs does not recreate the canvas, undo stack, data store or worker. The switcher displays a dot for active import, generation or other publishing work; detailed progress remains in the owning workspace. Preview-only rendering does not count as a production activity dot.
- External PDF opens and Open output PDF return to PDF Workspace. Use PDF background still modifies the current template.
- Ctrl+W closes the active PDF document or Designer project. Closing the last Designer project displays Create template / Open project / PDF envelope overlay, retaining Designer mode.

## Saving and shutdown

Closing a project checks its unsaved edits and invalid drafts. Save must succeed before closing; Cancel preserves the project. Discard authorizes closure without first destroying its model or draft.

Application shutdown performs all PDF and Designer confirmations before cancelling or removing work. If a later prompt is cancelled, earlier Discard choices have not cleared PDF form drafts or Designer drafts. Explicit Save/Apply choices remain saved, as requested. Once every confirmation succeeds, editing is disabled, jobs are cancelled at their existing safe checkpoints, and the event loop waits for PDF tasks, document readers and Designer worker cleanup. No blocking sleep is added to the GUI.

## Implementation

- `ui/workspace_modes.py`: stable `WorkspaceMode` values `pdf` and `designer`, segmented control, persistent mode stack, `request_mode`, `modeChanged`, focus retention and transitions.
- `ui/workspace_mode_controller.py`: lazy Designer host, mode-specific menus/commands/shortcut ownership, output-PDF routing, application close preflight and coordinated cleanup.
- `composition/designer/project_host.py`: template/overlay tabs, canonical path identity, collision protection, project-close confirmation and empty state.
- `core/viewer.py`: hooks into the existing root layout, open queue, motion preference, command discovery and close lifecycle. Existing PDF workspace/session processing remains in place.
- Template and overlay windows accept an `embedded` option; their standalone behavior remains supported. Overlay toolbar icons now update with the shared application theme.
- `ui/command_bar.py` replaces the launch button with the mode control; `ui/task_bar.py` publishes its activity state for the PDF mode indicator.

No new dependency, public version change, template migration, restart recovery or automatic resume. Composition engines remain independent of Qt. The existing Composition development feature flag controls integration. The stable checkout and packaged executables have not been changed.

## Focused validation

- **35 passed in 54.07 s**: 18 new mode cases, feature-gated entry cases, existing Designer/overlay interactions, scoped shortcut protection and PDF shortcut override compatibility.
- **2 passed in 6.86 s**: separate process with `QT_SCALE_FACTOR=2`, 960x640, light and dark themes.
- **1 passed in 3.34 s**: active overlay toolbar icons follow the shared light/dark theme.
- Total: **36 distinct related cases**, with two repeated at 200% scaling (**38 test executions**).
- The mode tests include actual active-tab Save/reopen, overlay Save-on-close/reopen, a real CSV import and two-record PDF generation while PDF mode is displayed, tab closure during import, cancelled application exit with both a PDF form draft and an active Designer job, and approved exit waiting for a PDF task checkpoint.
- Interaction tests suppress font inventory and unnecessary previews; production/save cases use the real subprocess worker. UI cases use the offscreen Qt platform. This verifies widget behavior and layout constraints, rather than claiming physical Windows monitor or installer acceptance.
- Changed-file Ruff and `git diff --check` pass.

Per the user's instruction, full regression, large performance jobs and Windows packaging remain deferred until the modification batch is complete. Manufacturer-specific insertion barcode presets still require actual machine specifications.
