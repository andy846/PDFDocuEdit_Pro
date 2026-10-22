# Release Validation — 3.1.1

## Source and scope

Owner confirmed source UAT on `0e25c15` and authorized direct public Windows
update-only v3.1.1 release and main
synchronization on 2026-10-23 (Hong Kong). Canonical workspace
`D:/Python_Project/PDFdocuEdit_Pro`, local branch `main`.
Installer, Portable and macOS artifacts are out of scope.

| Item | Completed evidence |
|---|---|
| Version / tag | 3.1.1 / v3.1.1 |
| Frozen product source | `8fdad474a2bbb27214917fe477720016b47d0ead` |
| Source fingerprint | `bc7cd96c88a70c96f43c986d23a80112e6b3cf39d0423d58402359ed7696d6a7` |
| Product base | `0e25c156544dfc7a9e0cfec28b56c6dc4b09058d` |
| Main synchronization | Ordinary fast-forward from `991b6b34a09fde5a05e637c1cada4e0e10f7a6cc` to frozen source |
| Native run | [39824573338](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39824573338), exact frozen SHA |
| Source quality / general main CI | [39824571785](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/39824571785) |
| Public release | [v3.1.1](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.1.1), latest, non-prerelease |
| Published UTC | 2026-10-22T18:21:14Z |

No branch/worktree was created, switched or merged. No force push or old tag
movement. The untracked operator profile and all local credentials/settings were
excluded. Completion records on main are separate from the immutable product tag.

## Acceptance and validation

| Check | Actual result |
|---|---|
| Local release contracts | 16 passed; source verification, repository Ruff and whitespace checks passed |
| Windows complete isolated native regression | 223 exact tracked modules; 3545 passed / 3 skipped; 0 failures/errors; evidence hash verified |
| Windows native update-only package | Passed; identical private/legacy ZIP bytes; no installer/portable archives |
| Frozen login-ready / unauthenticated workers | Passed; composition, print and PDF operations worker admission checked |
| Original frozen Launcher two upgrades | Passed: 3.0.3 → 3.1.0 → 3.1.1; original Launcher and settings retained |
| Upgrade credential isolation | Passed; private local data, require-signin marker and blocked network |
| Owner acceptance | Owner explicitly replied “已驗收” and requested direct publication |
| New frozen candidate real-account login | Pending / Not Tested independently; not inferred from owner acceptance or login-ready smoke |
| Candidate provenance, manifests and signatures | Passed using existing validators and trust anchor |
| Draft asset names/sizes/SHA256 | Passed; exact 10 assets checked by standard publisher |
| Public tag/latest and both anonymous Windows update routes | Passed; frozen SHA, signatures and ZIP links verified |
| Installer / Portable / macOS output | Out of scope |
| Real customer workflows / physical printer / RIP / inserter on v3.1.1 | Not Tested on this candidate |

The owner's “已驗收” was received before the new frozen package existed.
It is preserved as owner acceptance of the directed publication, not relabelled
as an observed account login. `windows_account_login=false` remains in the
source-bound acceptance record. The standard make-public operator gate was not
changed; promotion used the separately recorded owner-directed publication
exception after every other native, source, signing, upgrade and exact asset gate.
Earlier hardware/customer/login acceptance remains in its own version record.
The current source feature UAT is owner-confirmed; independent frozen candidate
login and physical-equipment acceptance are not inferred from that statement.

General main CI at evidence collection: Source quality: success, Select test scope: success, Core tests on ubuntu-latest: success, Automated suite on Windows: success, UI interaction tests on Windows: success, Core tests on macos-14: success, Affected tests and smoke on Windows: skipped.
The native Windows candidate regression above remains the release gate; general
CI results are recorded separately and never substituted for candidate evidence.

## Stage timings (UTC)

| Stage | Start | End | Duration |
|---|---|---|---|
| Source preparation | 2026-10-22T17:36:36.030720+00:00 | 2026-10-22T17:38:22.317361+00:00 | 106.29 s |
| Full isolated regression | 2026-10-22T17:40:51Z | 2026-10-22T18:12:33Z | 1902.00 s |
| Native account release candidates | 2026-10-22T18:12:33Z | 2026-10-22T18:14:57Z | 144.00 s |
| download | 2026-10-22T18:16:20.603194+00:00 | 2026-10-22T18:17:20.771325+00:00 | 60.17 s |
| candidate-validation | 2026-10-22T18:17:20.775418+00:00 | 2026-10-22T18:17:22.914908+00:00 | 2.14 s |
| seal | 2026-10-22T18:17:22.943590+00:00 | 2026-10-22T18:17:29.617672+00:00 | 6.67 s |
| isolated-upgrades | 2026-10-22T18:17:29.620591+00:00 | 2026-10-22T18:18:06.924269+00:00 | 37.30 s |
| publication | 2026-10-22T18:18:06.925774+00:00 | 2026-10-22T18:21:15.028429+00:00 | 188.10 s |
| public-verification | 2026-10-22T18:21:15.030564+00:00 | 2026-10-22T18:21:29.097827+00:00 | 14.07 s |

Total wall-clock from source preparation to anonymous verification:
2693.07 seconds.
The full native suite ran for this frozen source; earlier targeted tests and
v3.1.0 evidence were not relabelled or reused as this candidate's full result.

## Delivery

Both Windows update ZIPs: 360,219,517 bytes each;
SHA256 `3c5f392c2a5ead211e0700b60eca9b3fe0bc8a9a6de963df71256aa995a36133`.
Existing Managed installations: **Help → Check for Updates**.
First-time installation uses an existing full installer; this version has none.
No Mac update is published. Older latest-only Mac updaters may report missing
Mac assets, while installed Mac applications remain usable.

Local progress, native index/evidence, source-bound owner direction, upgrade
results, signed index, hashes, stage logs and anonymous verification are retained
under `build/probes/release-v3.1.1/` and are not committed with private data.
Public asset hashes and metadata remain immutable.

Release notes: [v3.1.1](RELEASE_NOTES_3.1.1.md).
Process: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).
