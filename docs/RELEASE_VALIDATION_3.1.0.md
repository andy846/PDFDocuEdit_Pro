# Release Validation — 3.1.0

## Source and scope

Owner authorized direct public Windows update-only v3.1 release and main
synchronization on 2026-10-22 (Hong Kong). Canonical workspace
`D:/Python_Project/PDFdocuEdit_Pro`, local branch `main`.
Installer, Portable and macOS artifacts are out of scope.

| Item | Completed evidence |
|---|---|
| Version / tag | 3.1.0 / v3.1.0 |
| Frozen product source | `589213b44ee2267fa2d31f5d178adce5b5a380fd` |
| Source fingerprint | `4a8d0c75c1d90ffede0b5f130bfd21c008de86078bdbc3bedbcbb12419d15286` |
| Product base | `ea1030478c7b7277e34a4996eefb51c9a4346403` |
| Main synchronization | Ordinary fast-forward from `cfc19778e98a5ae86b967a864f6b6b0c8d34a5c8` to frozen source |
| Native run | [39641641706](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39641641706), exact frozen SHA |
| Source quality / general main CI | [39641608485](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39641608485) |
| Public release | [v3.1.0](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.1.0), latest, non-prerelease |
| Published UTC | 2026-10-21T17:39:33Z |

No branch/worktree was created, switched or merged. No force push or old tag
movement. The untracked operator profile and all local credentials/settings were
excluded. Completion records on main are separate from the immutable product tag.

## Acceptance and validation

| Check | Actual result |
|---|---|
| Local release contracts | 26 passed; source verification, repository Ruff and whitespace checks passed |
| Windows complete isolated native regression | 220 exact tracked modules; 3189 passed / 3 skipped; 0 failures/errors; evidence hash verified |
| Windows native update-only package | Passed; identical private/legacy ZIP bytes; no installer/portable archives |
| Frozen login-ready / unauthenticated workers | Passed; composition, print and PDF operations worker admission checked |
| Original frozen Launcher two upgrades | Passed: 3.0.3 → 3.0.11 → 3.1.0; original Launcher and settings retained |
| Upgrade credential isolation | Passed; private local data, require-signin marker and blocked network |
| Owner acceptance | Owner explicitly replied “標記為已驗收” and requested direct publication |
| New frozen candidate real-account login | Pending / Not Tested independently; not inferred from owner acceptance or login-ready smoke |
| Candidate provenance, manifests and signatures | Passed using existing validators and trust anchor |
| Draft asset names/sizes/SHA256 | Passed; exact 10 assets checked by standard publisher |
| Public tag/latest and both anonymous Windows update routes | Passed; frozen SHA, signatures and ZIP links verified |
| Installer / Portable / macOS output | Out of scope |
| Real customer workflows / physical printer / RIP / inserter on v3.1.0 | Not Tested on this candidate |

The owner's “標記為已驗收” was received before the new frozen package existed.
It is preserved as owner acceptance of the directed publication, not relabelled
as an observed account login. `windows_account_login=false` remains in the
source-bound acceptance record. The standard make-public operator gate was not
changed; promotion used the separately recorded owner-directed publication
exception after every other native, source, signing, upgrade and exact asset gate.
Published v3.0.11 hardware/customer/login acceptance remains in its own record.

General main CI at evidence collection: Source quality: success, Select test scope: success, Automated suite on Windows: success, UI interaction tests on Windows: success, Core tests on macos-14: success, Core tests on ubuntu-latest: success, Affected tests and smoke on Windows: skipped.
The native Windows candidate regression above remains the release gate; general
CI results are recorded separately and never substituted for candidate evidence.

## Stage timings (UTC)

| Stage | Start | End | Duration |
|---|---|---|---|
| Source preparation | 2026-10-21T17:07:19+00:00 | 2026-10-21T17:11:38.299620+00:00 | 259.30 s |
| Full isolated regression | 2026-10-21T17:13:44Z | 2026-10-21T17:33:06Z | 1162.00 s |
| Native account release candidates | 2026-10-21T17:33:06Z | 2026-10-21T17:34:48Z | 102.00 s |
| download | 2026-10-21T17:35:54.474232+00:00 | 2026-10-21T17:36:54.388368+00:00 | 59.91 s |
| candidate-validation | 2026-10-21T17:36:54.389358+00:00 | 2026-10-21T17:36:55.686915+00:00 | 1.30 s |
| seal | 2026-10-21T17:36:55.687926+00:00 | 2026-10-21T17:36:59.874432+00:00 | 4.19 s |
| isolated-upgrades | 2026-10-21T17:36:59.875527+00:00 | 2026-10-21T17:37:27.658549+00:00 | 27.78 s |
| publication | 2026-10-21T17:37:27.660101+00:00 | 2026-10-21T17:39:34.354345+00:00 | 126.69 s |
| public-verification | 2026-10-21T17:39:34.356343+00:00 | 2026-10-21T17:39:45.909335+00:00 | 11.55 s |

Total wall-clock from source preparation to anonymous verification:
1946.91 seconds.
The full native suite ran for this frozen source; earlier targeted tests and
v3.0.11 evidence were not relabelled or reused as this candidate's full result.

## Delivery

Both Windows update ZIPs: 360,201,715 bytes each;
SHA256 `b2adabe482e3ce1d3e7cb225b6e45834e80091852c880d550bda40e69028f806`.
Existing Managed installations: **Help → Check for Updates**.
First-time installation uses an existing full installer; this version has none.
No Mac update is published. Older latest-only Mac updaters may report missing
Mac assets, while installed Mac applications remain usable.

Local progress, native index/evidence, source-bound owner direction, upgrade
results, signed index, hashes, stage logs and anonymous verification are retained
under `build/probes/release-v3.1.0/` and are not committed with private data.
Public asset hashes and metadata remain immutable.

Release notes: [v3.1.0](RELEASE_NOTES_3.1.0.md).
Process: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).
