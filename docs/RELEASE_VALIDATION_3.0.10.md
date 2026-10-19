# Release Validation — 3.0.10

## Source and scope

Owner requested Windows upgrade updates only and direct public publication on
2026-10-19. Installer, Portable and macOS are explicitly out of scope. Public
publication is authorized; incomplete verification is not an accepted result.

| Item | Record |
|---|---|
| Version / tag | 3.0.10 / v3.0.10 |
| Repository / product workspace | andy846/PDFDocuEdit_Pro / `D:/Python_Project/PDFdocuEdit_Pro` |
| Current development branch | `codex/deep-search-restore-layout`, retained |
| Previous product HEAD | `bef974b4f555796ceb57d70cf7f7b8600176a554` |
| Frozen SHA / fingerprint | Pending; candidate metadata and local release ledger record the freeze |
| Release ref | Existing `codex/windows-update-v3.0.8`; fast-forward only, no new branch or checkout |
| Native workflow / run headSha | Pending |
| Candidate / signed index / attachment hashes | Pending |
| Local progress and evidence | `build/probes/release-v3.0.10/` |
| Release URL / publication | Pending |

The pre-existing remote release ref is reused to preserve the owner's single
local development line and avoid creating/switching branches. The unified native
workflow is dispatched with `release_scope=windows-update`. Existing public tags
and attachments are immutable. The local untracked operator profile is excluded
from staging, builds and publication; it is not read or changed.

## Acceptance

| Check | Status | Evidence |
|---|---|---|
| Metadata/source/release contracts | Pending | Version and source checks before freeze |
| Windows complete isolated regression | Pending | Exact frozen-source native run required |
| Native Windows update-only packaging | Pending | Private and legacy update ZIPs, no installer/portable |
| Frozen login-ready / unauthenticated worker rejection | Pending | Native candidate checks |
| Existing Launcher successive upgrades | Pending | Isolated test installations; user application remains open |
| Current candidate real-account login | Pending | Must be independently confirmed for this SHA |
| Candidate provenance / signed index / both signed update routes | Pending | Existing validators and trust anchor |
| Draft remote filenames / sizes / SHA256 | Pending | Unified publish validator |
| Operator acceptance matches frozen SHA | Pending | No untested fields set true |
| Public tag / manifests / signatures / downloads | Pending | After authorized publication |
| Installer / Portable / Mac | Out of scope | Explicit Windows update-only instruction |
| Physical printer / RIP / inserter / real customer jobs | Not tested | Software fixtures do not certify equipment |

Prior development regression reports are historical evidence, not substituted
for the frozen release candidate. Existing signing/publication gates are retained.

## Timing and recovery

| Stage | Start / end / duration | Result / continuation |
|---|---|---|
| Source preparation | Pending | Local ledger records UTC and elapsed times |
| Windows native regression / packaging | Pending | Keep completed job/artifact progress on failure |
| Download / validation | Pending | Resume missing downloads only |
| Signing | Pending | Existing owner key; no credentials in release assets |
| Draft upload / remote verification | Pending | Resume matching assets, never overwrite |
| Operator acceptance | Pending | Candidate-specific upgrades and login |
| Public release / post-publication verification | Pending | Public/latest only after required evidence |

## Delivery

- Windows update download / Release URL: Pending.
- Mac download: none for this version; the Windows-only latest limitation is
  documented in release notes. Installed Mac applications remain usable.
- No public completion is claimed while any required gate remains incomplete.
