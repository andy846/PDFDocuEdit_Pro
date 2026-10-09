# Private Windows access — validation, 2026-10-09

Baseline: v3.0.3, `85b57d4`. Implementation is isolated on
`codex/supabase-private-login`; no public version, template format, installer ID
or update release was changed. Public default builds remain authentication-free.

## Completed

| Gate | Evidence |
|---|---|
| Complete existing regression | 154 modules, 2,132 tests passed; zero failures/errors/skips, `build/auth-regression/result.json` |
| Final affected auth/build/startup tests | 46 passed after final source fixes, including real Windows Credential Manager QA namespace and pinned SDK MockTransport |
| Source verification and Ruff | Passed |
| Adjacent CI/printing/task/portable checks | 23 passed; printing module separately rechecked, 7 passed |
| Dependency consistency | `pip check` passed; Supabase 2.32.0 and keyring 25.7.0 with pinned optional dependency lock |
| Secure cache/revocation | Corrupt/mismatched cache, late verification after logout, deletion-failure restart block, offline approval, single-flight checks |
| Recovery | Locked production worker creates no IPC/output; template draft save reuses serializer in owned thread without worker IPC |
| Frozen payload | Required public configuration, Supabase SDK, Windows keyring backend and admission guard present in PYZ |
| Frozen worker admission | Four worker/QA flags reject unapproved Windows user even with `PDFDOCUEDIT_ENABLE_AUTH=0`; no unauthorized template created |
| Real Managed Portable launcher | Login shell acknowledged readiness before sign-in, 1.83 seconds in this local run |
| Actual Setup install/launch/uninstall | Dedicated fresh worktree QA folder; login readiness 1.83 seconds; install and uninstall successful |
| Existing file associations | Compared before/after private Setup; unchanged |
| Distribution safety | Private build/deployment scans passed; PEM allowance limited to exact installed certifi public CA bundle |
| Actual Build Kit | 1,692 allowlisted files, 185,233,265 bytes; private names absent and new auth sources present |
| UI fixtures | Login, account, recovery and account entry in both modes rendered/inspected at logical 960×640, dark/100% and light/200% |

UI rendering used Qt offscreen fixtures with Segoe UI explicitly loaded because
the offscreen plugin does not discover Windows system fonts. This verifies
widget layout, not native multi-monitor/DPI behaviour. Desktop inspection helper
failed to start; no claim of live desktop visual acceptance is made.

This machine emits handled Windows COM printer-enumeration diagnostics
(`0x80040155`) when Qt creates QPrinter, including in the earlier complete
regression log. The isolated repeat exited 0 with 7 passing assertions; no test
was disabled. Actual printer spooling remains outside this auth acceptance.
The pinned certifi bundle also triggers a cryptography certificate serial-number
deprecation warning; bundle validation still passes.

Packaged checks use the **real frozen Launcher and application**. They stop only
their own empty unauthenticated QA child after handshake; they do not simulate a
successful human login or graceful close of an authenticated unsaved workspace.
Evidence: `build/private-packaged-final-2/result.json`.

## Internal artifacts

- `release/PDFDocuEdit-Pro-v3.0.3-Private-Auth-Managed-Portable-Windows-x64.zip`
  SHA256: `3fc85690a46cc275fa3c8f1add881a97fa1a74ada8c7c16e7f163ee7c6fdc3a1`
- `release/PDFDocuEdit-Pro-v3.0.3-Private-Auth-Setup-Windows-x64.exe`
  SHA256: `4f28832c51d17822fddfba26d228fb779098ca55262dbbcaf8cf78b988db59cc`

These artifacts are internal test outputs, not GitHub Releases or signed update
packages. No production update private key was used.
Product artifacts were built at `690b0a9`; later commits add documentation and
source-only QA scripts, with no application-code changes.

## Owner-assisted gates still pending

### GitHub CI follow-up

The first PR CI run passed Windows core, macOS/Linux core and source quality.
Private auth UI tests passed too. The Windows UI job failed with a native access
violation in the existing Organizer audit module during shortcut construction.
That module created per-test QApplication instances rather than requesting the
existing retained session fixture. It now uses `qt_application` for the entire
module; all 13 assertions pass locally. No tests/assertions were removed. Remote
CI must confirm this lifecycle correction before the PR leaves draft.

### Live backend onboarding

The owner subsequently requested one account to be provisioned through the
normal Supabase Auth API. Its allowlist grant is active; email confirmation is
still required before real login acceptance. No password/account identity is
stored in this repository. Public signup is still enabled; anonymous login is
disabled. Owner-assisted account/security gates below remain pending.

- Real approved/unapproved account login, wrong passwords and session expiry.
- Actual backend cross-account isolation using two provisioned users.
- Live revocation while PDF/Designer/Workflow have unsaved work; save/re-login
  and logout cancellation with actual credentials.
- Owner disables public signup and provisions a second isolated test account
  for cross-account checks. Anonymous login is already disabled; one approved
  account awaits email confirmation.
- Native desktop layout/DPI and a second Windows machine.

Read-only backend inspection confirmed the applied migration, own-row RLS and
SELECT-only grants; security/performance advisors returned no lints. No backend
schema/settings/account changes were made to bypass pending owner actions.

## Reproduce

```powershell
python -m pytest -q tests/test_private_auth.py tests/test_private_auth_ui.py tests/test_private_auth_sdk.py tests/test_private_auth_build.py tests/test_entrypoint.py tests/test_update_release.py
python scripts/regression_suite.py --group all --output build/auth-regression-new
python scripts/build_private_auth.py
python scripts/private_auth_packaged_qa.py --output build/private-packaged-new
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_SCALE_FACTOR = '2'
python scripts/private_auth_ui_qa.py --theme light --output build/private-ui-new
```

Packaged QA requires no existing private Setup/secure approval and a fresh output
folder under this worktree's `build`. It refuses to replace an existing private
installation or erase another user's approval. Source fixture rendering sends no
account requests and uses no real Windows credentials.
