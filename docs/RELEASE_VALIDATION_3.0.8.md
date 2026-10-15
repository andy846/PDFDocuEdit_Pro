# Release Validation — 3.0.8

## Scope

Owner requested Windows update packages only. Installer, Portable, macOS native builds and Mac operator gates are out of this release scope; no successful results are fabricated for them. Full Windows native regression, frozen login/worker gates, update integrity and legacy compatibility remain required.

## Source and evidence

- Version / tag: 3.0.8 / v3.0.8
- Branch: codex/windows-update-v3.0.8
- Workspace: existing print-composition-v3 product worktree
- Frozen source commit / fingerprint: Pending freeze
- Native workflow / candidates / signing / release: Pending

## Acceptance

| Check | Status | Evidence |
|---|---|---|
| Windows complete isolated regression | Pending | |
| Windows native update-only packaging | Pending | |
| Frozen login-ready / unauthenticated worker denial | Pending | |
| Signature / source / target / package integrity | Pending | |
| Original Launcher compatibility / successive updates | Pending | |
| Candidate real-account login | Pending | |
| Remote attachment hashes / public downloads | Pending | |
| macOS / Installer / Portable | Out of scope | Owner's explicit Windows-update-only request |

## Limits

Latest release contains no Mac update manifest; older Mac update checks report a missing Mac attachment. Existing Mac installation remains v3.0.7. The reported customer's slow PS conversion remains uncharacterised; v3.0.8 repairs visibility, not a verified throughput cause. No printer hardware acceptance or unperformed operator check is claimed.
