# Private Windows account build (Issue #9)

This is an isolated internal acceptance build on v3.0.3. Public Windows/Mac
builds remain authentication-free. No public release/version/format change.
Do not merge or distribute as a public update until the owner accepts the tests.

## Behaviour

1. First sign-in requires internet, server-verified identity and an active own
   row in `public.app_access`. No registration screen is provided.
2. Windows Credential Manager stores approval and refresh token for this
   Windows user/project. No session/token/password is written to settings,
   worker requests, command lines, plain files or application logs.
   An empty, non-secret `require-signin` marker under the user's local app-data
   directory blocks cached approval after sign-out/revocation, including when
   Windows refuses credential deletion. Verified sign-in removes that marker.
3. Saved approval permits offline launches without expiry. One background
   check starts after launch, then every 10 minutes. HTTP requests time out
   after 10 seconds each. Network/5xx/malformed responses retain approval.
4. Invalid refresh/session prompts re-login while retaining offline approval.
   Only a valid server identity plus absent/inactive own access row confirms
   revocation. An indefinitely offline client cannot guarantee remote revocation.
5. Confirmed revocation clears approval, locks new work and cancels unfinished
   work cooperatively. Already published/printed output cannot be recalled.
   The recovery screen retains open work and permits save/re-login/exit.
   Save-only recovery calls the existing serializers in an owned local thread;
   it cannot compose/print/export production output or admit a worker process.
6. Sign out reuses existing save/close confirmation and safe worker cleanup.
   Cancel leaves the original account approved. Different accounts cannot
   inherit the prior account's workspace; same-account re-login can resume it.
7. Account details are available beside Preferences in **More commands** in PDF
   mode, or **Settings** in the main/Designer menu. The entry shows the signed-in
   email, including while using saved offline approval; it uses no toolbar space.
   The branded sign-in screen follows the application theme, supports keyboard
   submission, validates empty inputs and clears/hides the password on submission.
   Public updater actions are
   disabled in this test build to prevent installing an authentication-free
   public package over a private build. Future private updates need their own
   channel. This gate is not tamper-proof DRM against a local administrator.

## Setup and owner actions

The public project configuration is `build_assets/auth/PROJECT.json`.
It contains a publishable client key, never a secret/service-role/admin key.
Project `fbzelgtsfoedguyyvxqv` already has migration `20261009035228` applied.
The matching SQL here is a local baseline; **do not replay CREATE** on that project.
RLS exposes only the authenticated user's own access row, with SELECT only.

Before real acceptance, the project owner must:

- Disable **Allow new users to sign up** and **Anonymous sign-ins** in Auth settings.
- Privately provision 1–2 test accounts; do not post passwords to GitHub/chat.
- Add their UUIDs to `app_access` and activate approved users as administrator.
- Confirm login, wrong password, inactive access, offline restart, revoked
  access during unsaved PDF/Designer/Workflow work, and sign-out cancellation.

Inspection on 2026-10-09: RLS/grants/migration verified; security/performance
advisors reported no lints. No accounts existed and `disable_signup` was false.
These are acceptance blockers, not claims of completed backend onboarding.
Do not put owner/admin credentials into the desktop build to resolve them.

## Develop and package

Use a separate Windows Python 3.12 environment:

```powershell
python -m pip install -r requirements-windows.txt -r requirements-dev.txt -r requirements-auth-windows.lock
$env:PDFDOCUEDIT_ENABLE_AUTH = '1'
python main.py
```

Source auth is opt-in. Frozen auth builds embed required public configuration
in their PYZ and cannot disable authentication with that environment setting.
Only explicit private builds bundle the optional SDK/keyring dependencies.

```powershell
python scripts/build_private_auth.py
```

Outputs have `Private-Auth` names. Setup uses a separate installer ID/folder and
does not register file associations. Managed Portable uses the existing
launcher/readiness protocol: the login shell can acknowledge readiness before
human sign-in or network results. Incoming files queue until approval **and**
managed acceptance. Test packages do not use the production update signing key,
create release tags or publish GitHub Releases. Existing application/QSettings
preferences may still be shared during developer testing; managed project
settings use their separate deployment root. No first-run migration prompt is
shown before private-shell readiness.

Workers and protected QA entries check local secure approval before dispatch.
Parent dispatch also checks current in-memory state after revocation.
Composition/PDF engines have no Supabase or GUI dependencies added.

The Build Kit includes Git-tracked sources and explicit runtime roots only,
hard-excluding credentials, developer state, logs and virtual environments.
Distribution scanning allows PEM only for the exact certifi CA-bundle location,
matching the installed pinned public certificate bundle, with no private keys.

## Acceptance evidence

```powershell
python -m pytest -q tests/test_private_auth.py tests/test_private_auth_ui.py tests/test_private_auth_build.py tests/test_update_release.py tests/test_entrypoint.py
python scripts/regression_suite.py --group all --output build/auth-regression
```

Automated checks cover secure-store round-trip/corruption, sanitized SDK errors,
server identity, active/inactive/malformed access rows, offline cache retention,
single-flight requests, stale results after sign-out, managed path routing,
logout cancellation, account switch isolation, retained revoked workspace,
Unicode passwords, narrow login layout and packaging exclusions. Real account
acceptance and a second Windows machine remain separate owner-assisted gates.

See [owner setup runbook](SUPABASE_AUTH_SETUP.md) and
[validation results and pending gates](PRIVATE_AUTH_VALIDATION.md).
