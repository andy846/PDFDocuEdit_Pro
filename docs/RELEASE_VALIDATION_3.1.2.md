# Release Validation — 3.1.2

## Source and scope

Owner confirmed source UAT on `3b710c5` and authorized direct public Windows
update-only v3.1.2 release and main
synchronization on 2026-10-29 (Hong Kong). Canonical workspace
`D:/Python_Project/PDFdocuEdit_Pro`, local branch `main`.
Installer, Portable and macOS artifacts are out of scope.

| Item | Completed evidence |
|---|---|
| Version / tag | 3.1.2 / v3.1.2 |
| Frozen product source | `fd1295a7ec30b46474fbb90afe7a6a4472dd5d7c` |
| Source fingerprint | `676b46b6ddd78c6077c31239343bd1b704f0bc93870122a423b20cfb7fbb5d37` |
| Product base | `3b710c594b9ac8b7cd20b248468ba4e30dc77de3` |
| Main synchronization | Ordinary fast-forward from `a794cbea68cf51972f50864e4f45a6bf303455ed` to frozen source |
| Native run | [40795930656](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/40795930656), exact frozen SHA |
| Source quality / general main CI | [40795904087](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/40795904087) |
| Public release | [v3.1.2](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/v3.1.2), latest, non-prerelease |
| Published UTC | 2026-10-29T01:23:10Z |

No branch/worktree was created, switched or merged. No force push or old tag
movement. The untracked operator profile and all local credentials/settings were
excluded. Completion records on main are separate from the immutable product tag.

## Acceptance and validation

| Check | Actual result |
|---|---|
| Local release contracts | 16 passed; source verification, repository Ruff and whitespace checks passed |
| Windows complete isolated native regression | 227 exact tracked modules; 3603 passed / 3 skipped; 0 failures/errors; evidence hash verified |
| Separate main CI Windows UI regression | 82 modules / 1,335 passed / 0 skipped, failures or errors; includes preview-raster and Organizer cases; not added to native totals |
| Windows native update-only package | Passed; identical private/legacy ZIP bytes; no installer/portable archives |
| Frozen login-ready / unauthenticated workers | Passed; composition, print and PDF operations worker admission checked |
| Original frozen Launcher two upgrades | Passed: 3.0.3 → 3.1.1 → 3.1.2; original Launcher and settings retained |
| Upgrade credential isolation | Passed; private local data, require-signin marker and blocked network |
| Owner acceptance | Owner explicitly replied “已驗收” and requested direct publication |
| New frozen candidate real-account login | Pending / Not Tested independently; not inferred from owner acceptance or login-ready smoke |
| Candidate provenance, manifests and signatures | Passed using existing validators and trust anchor |
| Draft asset names/sizes/SHA256 | Passed; exact 10 assets checked by standard publisher |
| Public tag/latest and both anonymous Windows update routes | Passed; frozen SHA, signatures and ZIP links verified |
| Installer / Portable / macOS output | Out of scope |
| Real customer workflows / physical printer / RIP / inserter on v3.1.2 | Not Tested on this candidate |

The owner's “已驗收” was received before the new frozen package existed.
It is preserved as owner acceptance of the directed publication, not relabelled
as an observed account login. `windows_account_login=false` remains in the
source-bound acceptance record. The standard make-public operator gate was not
changed; promotion used the separately recorded owner-directed publication
exception after every other native, source, signing, upgrade and exact asset gate.
Earlier hardware/customer/login acceptance remains in its own version record.
The current source feature UAT is owner-confirmed; independent frozen candidate
login and physical-equipment acceptance are not inferred from that statement.

General main CI at evidence collection: Source quality: success, Select test scope: success, Automated suite on Windows: success, UI interaction tests on Windows: success, Affected tests and smoke on Windows: skipped, Core tests on ${{ matrix.os }}: skipped.
The native Windows candidate regression above remains the release gate; general
CI results are recorded separately and never substituted for candidate evidence.

## Superseded first candidate checks

Main CI run 40793773821 at `b9f4a7421c04e9683841278b9f28fe998d086e55`
failed the preview-raster and Organizer auto-scroll UI cases. Native run
40793774297 was cancelled as superseded and cannot qualify this release.
The preview case's idle-worker/debounced-replacement race was reproduced locally
with an extended debounce; the corrected test waits for the committed page raster
and inactive timer, retaining all drawing-safety and geometry assertions.
Its full module then passed 16 cases. The Organizer failure was not reproduced
in local targeted/full-module runs (10 module cases); production code and test
assertions were unchanged. The new exact-source native and main CI runs listed
above passed before publication. Original logs, diagnostics and progress remain
under `build/probes/release-v3.1.2/ci-failure/` and `attempt-01/`.

## Stage timings (UTC)

| Stage | Start | End | Duration |
|---|---|---|---|
| Source preparation | 2026-10-29T00:21:27.735621+00:00 | 2026-10-29T00:43:20.019769+00:00 | 1312.28 s |
| Full isolated regression | 2026-10-29T00:44:55Z | 2026-10-29T01:15:44Z | 1849.00 s |
| Native account release candidates | 2026-10-29T01:15:44Z | 2026-10-29T01:17:51Z | 127.00 s |
| download | 2026-10-29T01:19:08.282914+00:00 | 2026-10-29T01:19:51.750116+00:00 | 43.47 s |
| candidate-validation | 2026-10-29T01:19:51.751121+00:00 | 2026-10-29T01:19:52.823666+00:00 | 1.07 s |
| seal | 2026-10-29T01:19:52.824665+00:00 | 2026-10-29T01:19:56.258626+00:00 | 3.43 s |
| isolated-upgrades | 2026-10-29T01:19:56.260624+00:00 | 2026-10-29T01:20:25.991345+00:00 | 29.73 s |
| publication | 2026-10-29T01:20:27.729023+00:00 | 2026-10-29T01:23:10.562673+00:00 | 162.83 s |
| public-verification | 2026-10-29T01:23:10.563681+00:00 | 2026-10-29T01:23:22.129890+00:00 | 11.57 s |

Total wall-clock from source preparation to anonymous verification:
3714.40 seconds.
The full native suite ran for this frozen source; earlier targeted tests and
v3.1.1 evidence were not relabelled or reused as this candidate's full result.

## Delivery

Both Windows update ZIPs: 360,273,195 bytes each;
SHA256 `e9a85a83938151265878e32d6034fb4c694679db6984e9115172c6dd69d1057f`.
Existing Managed installations: **Help → Check for Updates**.
First-time installation uses an existing full installer; this version has none.
No Mac update is published. Older latest-only Mac updaters may report missing
Mac assets, while installed Mac applications remain usable.

Local progress, native index/evidence, source-bound owner direction, upgrade
results, signed index, hashes, stage logs and anonymous verification are retained
under `build/probes/release-v3.1.2/` and are not committed with private data.
Public asset hashes and metadata remain immutable.

Release notes: [v3.1.2](RELEASE_NOTES_3.1.2.md).
Process: [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).
