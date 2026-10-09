# Private account setup — owner runbook

Use the dedicated test project, not an unrelated production Supabase project.
The desktop client uses a **publishable** key only. Never embed a secret,
service-role key, admin token or test password in source, CI or packages.

## 1. Close public registration

In the Supabase Dashboard, open the project's Authentication settings:

1. Turn off **Allow new users to sign up**.
2. Turn off **Allow anonymous sign-ins**.
3. Save and verify the effective settings. Having no signup button in the app
   does not disable the public signup API.

The project was inspected on 2026-10-09: signup was still enabled and no test
accounts existed. These settings require owner action before private rollout.

## 2. Provision accounts privately

In Authentication → Users, use the administrator's create/invite-user action.
Provision 1–2 approved test accounts and an unapproved test account if needed.
Give credentials to their owners privately; never paste passwords into Codex,
GitHub issues, screenshots, test requests or application configuration.

Copy the approved user's UUID. In the project's SQL editor, run as owner:

```sql
insert into public.app_access (user_id, is_active)
values ('REPLACE_WITH_AUTH_USER_UUID'::uuid, true)
on conflict (user_id) do update set is_active = excluded.is_active;
```

The baseline migration `20261009035228_create_pdfdocuedit_app_access` is already
applied. Do not replay its CREATE statements. `app_access` must have RLS on,
SELECT restricted to the authenticated user's own UUID, and no client write
permission. The local migration records this existing baseline.

## 3. Install the private acceptance build

Use the **Private-Auth Setup** in an isolated folder, or extract the entire
**Private-Auth Managed Portable** ZIP to an empty folder and run `Launcher.exe`.
This test channel has a separate installer ID and does not register public file
associations. Public updates are disabled. No public version was changed.

First sign-in requires internet. Approval and the refresh token are stored in
Windows Credential Manager for this Windows user and Supabase project.
Subsequent launches can work offline indefinitely, per the approved plan.
Remote revocation cannot be guaranteed while a machine remains offline.

## 4. Acceptance checklist

- Approved account: login, PDF Workspace, Template Designer and Workflow work.
- Wrong password: no workspace admitted; message contains no server payload.
- Unapproved/inactive account: no workspace admitted.
- Offline restart after approval: existing work tools remain available.
- Account → Check now: refreshes server identity and own access status.
- Sign out → cancel an unsaved-work prompt: retains the original account/work.
- Sign out → save/close: returns to login and clears/blocks local approval.
- Different account: must close the old workspace before admission.
- Same account re-login: resumes retained locked work.
- Public signup/anonymous requests are rejected by the backend.
- With two test accounts, each can read only its own `app_access` row and cannot
  change `is_active`. Verify using authenticated client credentials privately.

To revoke an approved test account as owner:

```sql
update public.app_access
set is_active = false
where user_id = 'REPLACE_WITH_AUTH_USER_UUID'::uuid;
```

When online, the next check (every ten minutes, or **Check now**) must retain
unsaved PDF/Designer/Workflow work, block new work and offer save/re-login/exit.
Already published or printed output cannot be recalled. Re-enable the own row
and sign in again to test recovery. Delete the row to test the absent-row case.

## 5. Troubleshooting and key changes

- Connection/timeout/5xx: saved offline approval is retained; check again later.
- Invalid refresh session: re-login restores verification; it is not treated as
  proof that `app_access` was revoked.
- Credential-store failure: do not fall back to JSON settings or plain files.
  An empty `require-signin` marker blocks reuse after revocation/sign-out.
- Public client key change: update `build_assets/auth/PROJECT.json` with the
  new publishable key, rebuild and repeat packaged acceptance. Do not distribute
  an admin key to avoid rebuilding the client.
- New project: approvals are isolated by project reference; provision accounts
  and verify the new backend's RLS/grants before building.

See [implementation and limits](PRIVATE_AUTH.md) and
[recorded validation](PRIVATE_AUTH_VALIDATION.md). This is a desktop access gate,
not protection against a local administrator patching the application.
