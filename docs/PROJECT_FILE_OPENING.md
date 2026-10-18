# Designer project shell opening (Windows / macOS)

## Confirmed defect

`main.pdf_arguments` accepted `.pdcx` and `.pdflow` only on macOS. On Windows,
startup and single-instance forwarding discarded those command-line paths.
`main.route_open_files` also sent all Windows incoming requests to the PDF queue,
bypassing the Designer project host. The Windows installer registries advertised
PDF/PS/EPS but did not advertise Designer projects.

## Repair

- Accept case-insensitive `.pdcx` / `.pdflow` alongside the existing PDF/PS/EPS
  arguments, preserving absolute paths, spaces and request order.
- Send project requests to the existing `DesignerProjectHost.open_project` with
  `create_default=False`; only a successful open requests Designer mode. Existing
  host format recognition selects Template, Overlay or Visual Workflow, so a
  `.pdcx` Overlay is not incorrectly forced into a Template tab.
- Requests received after exit approval do not create new projects.
- Reopening an existing project selects its existing tab. No project loader,
  serializer, data import or production engine is duplicated or changed.
- PDF-only Windows requests retain the existing batched PDF queue and last-active
  PDF-window routing. macOS retains its existing project handling. Login and
  Managed requests retain the existing readiness/approval gate before routing.
- Standalone and production Managed installer registries add project Open With /
  Default Apps capabilities. Standalone SupportedTypes also includes both project
  extensions. Existing Windows defaults and protected UserChoice are not overwritten;
  private-auth test installer association isolation is retained.

## Deployment and verification boundaries

The runtime repair takes effect for new launches of the modified application.
An already installed executable is not changed by editing development source.
Existing installations receive the runtime fix through a later normal update;
new installer registration applies when that installer is built and installed.
If Windows has no project association, choose PDFDocuEdit Pro using Open with.
A development Python launch does not silently claim Explorer file associations.

Tests cover argument filtering/order/case, mixed PDF/project routing, failed opens,
real Template/Overlay/Workflow host selection and deduplication, single-instance
IPC with project paths, existing authentication/startup/PDF multi-window behavior
and installer registry declarations. Registry tests inspect installer configuration;
they do not execute a native installer or prove Explorer association behavior.
Native macOS and a freshly installed Windows package remain separate acceptance.

Local test evidence: `build/probes/project-file-routing/` (not release assets).
No public version, format, dependency, branch, update key or release changes.

## Verification — 2026-10-17

- Initial RED: 8 failed / 1 passed, including Windows argument filtering,
  project dispatch, failed-open isolation, installer declarations and real
  Template/Overlay mode switching. GREEN: all 9 initial cases passed.
- Added a real Workflow host/reopen case and PDF/PDCX/PDFLOW local IPC cases.
- Ten related modules completed: 146 passed / 0 failed / 0 skipped.
- Exit-approval protection was then verified RED (1 failed) and GREEN:
  21 passed across the final routing/macOS-parity modules (8 + 13).
  The final unique per-module total is **147 passed**, including the added
  close-time case; this is not a full application regression claim.
- A final real-host shell-open rerun covers Template/Overlay/Workflow after
  the exit guard was added. Ruff and `git diff --check` passed.
- Automated tests ran on Windows with Qt offscreen. macOS routing is simulated
  on this host, not native macOS acceptance. Native installer/Explorer default
  selection was not exercised; no registry values were changed on this machine.
- No running application was closed or restarted during the repair. Existing
  unsaved projects remain with the user; a new launch is needed to load the fix.
