# Release Validation — 3.0.5

GitHub Draft candidate; not publicly released. This record does not claim unperformed operator tests passed. Follow [UNIFIED_RELEASE.md](UNIFIED_RELEASE.md).

## Frozen source

- Repository: `andy846/PDFDocuEdit_Pro`.
- Version/tag: `3.0.5` / `v3.0.5`.
- Product checkout: `macos-parity/PDFdocuEdit_Pro`, branch `codex/unified-release-v3.0.5`.
- Frozen source: `4900521f1b7dd8d26ec3d9ccd8693c790c4581f2`.
- Source fingerprint: `77ddd14692276711cea7561c998e9dce2dff9d077139274eeb5a394b163f3ec4`.
- Public baseline: v3.0.4, `037f89d256f8f09ae6e0796e9b19def47bff7b25`, retained unchanged.
- [Native candidate run 38124417858](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38124417858): both jobs Passed at the frozen source.
- [General CI 38124417877](https://github.com/andy846/PDFDocuEdit_Pro/actions/runs/38124417877): source quality Passed; duplicate focused execution omitted only on release branches, complete native gates retained.
- Evidence, candidate and signed files: `build/probes/release-v3.0.5-38124417858/` in the local development archive. No signing credentials are included in this record or public attachments.
- [Verified GitHub Draft](https://github.com/andy846/PDFDocuEdit_Pro/releases/tag/untagged-0d93f6130967808d34a7), Release ID `409555935`, all 20 attachments uploaded and verified by `scripts.unified_release publish`.

## Native gates

| Gate | Result | Evidence |
|---|---|---|
| Windows full isolated regression | Passed | 165 modules, 2,267 reported tests, 0 failures/errors, 3 existing skips; `windows/build/ci-release/result.json` |
| Windows native packaging | Passed | Managed Installer, Portable and both update routes; `candidate-windows-x64.json` |
| Windows frozen login readiness | Passed | Actual frozen Launcher accepted before login, 3.38s; not a real-account test |
| Unauthenticated workers | Passed | Composition, print and PDF-operation entry points rejected |
| Mac native regression | Passed | 33 modules, 539 reported tests, 0 failed modules, 2 existing skips; `macos/build/macos-tests/result.json` |
| Mac native packaging | Passed | arm64 Managed DMG/update, macOS 13+ deployment target; `candidate-macos-arm64.json` |
| Mac frozen login/Managed shell | Passed | Login readiness, worker rejection, duplicate/direct launch routing; real account not tested by CI |
| Source/platform/account provenance | Passed | Same version, full commit and fingerprint; sealed candidate validator checked packaged metadata |
| Update/index signatures | Passed | Existing trust key, all three manifest routes; `signed/release-index.json` and `.sig` |

Regression evidence SHA256:

- Windows: `ba15270abfece0f8e8b8ea0fe788b014671c664e5a0dd567c6dafd2bfe9b666b`.
- Mac: `d94d11d24da4f380d90d789c81a305c9cb5d2199946c387b561efe98b36ac3c4`.

The signed release index records each native candidate, packaged identity and public file name/size/SHA256. Legacy and private Windows update archives are identical. The private signing key is never sent to CI or GitHub.

Signed index SHA256: `7aff151f74931229a9d4d80ac9ce1d89509c32287a18671fd6aa4d4023d3f9da`.

## Operator gates

| Gate | Status | Evidence / missing action |
|---|---|---|
| Original Windows v3.0.3 Launcher, two upgrades | Passed | `build/probes/Q5/result.json`: 3.0.3 → actual frozen candidate 3.0.5 → separate QA-only 3.0.6 |
| Launcher and settings preservation | Passed | Original Launcher SHA256 `172dbae78ff8951e13de3aae4e3378d5a4a6995d03fc05e47a46814050d37522`, project-path sentinel unchanged |
| Windows real cached account / candidate UI | Pending | Isolated `build/probes/U5/PDFDocuEditPro` reaches main Workspace; desktop locked during visual capture, awaiting unlock/account UI confirmation |
| Mac candidate account login | Pending | Requires this candidate, not prior v3.0.4 confirmation |
| Mac offline reopening | Pending | Requires approved account on this candidate and actual disconnected reopening |
| Mac cross-version update | Pending | Signed candidate helper and operator report required |
| Draft remote name/hash/size checks | Passed | Unified publisher exited successfully; `remote-release.json` records all 20 attachments and GitHub SHA256 digests |
| Public tag/manifests/download routes | Pending | Not public until operator gates complete |

The follow-on v3.0.6 archive is a separately built/signed QA variant from the earlier preparation source. It solely exercises a second newer frozen version through the unchanged original Launcher. It is not a product release and must never be uploaded. Candidate acceptance and manifests remain bound to the actual v3.0.5 frozen source above.

The currently running user's application and documents were not terminated. UI inspection stopped immediately when a Windows PIN/locked-desktop screen appeared.

## Timings (UTC, 2026-10-11)

| Stage | Start | End / status |
|---|---|---|
| Preparation | 07:45:23 | Initial candidate superseded after real failures |
| Corrected Windows native job | 08:19:55 | 09:00:19, 40m24s |
| Windows complete regression | 08:21:20 | 08:52:38, 31m18s |
| Windows native packaging | 08:52:38 | 08:59:34, 6m56s |
| Corrected Mac native job | 08:19:59 | 08:35:22, 15m23s |
| Mac native packaging | 08:32:43 | 08:35:05, 2m22s |
| Signed index written | — | 09:03:31 |
| Draft upload / remote validation | 09:03 onward | Completed; saved in `remote-release.json` |
| Real-machine/operator wait | — | Pending desktop unlock and Mac checks |

Parallel native times are not added as total elapsed time. Download/sign/upload and operator waiting are distinct from test execution. No duplicate local complete suite was run after corrected native success.

## First candidate superseded; regression fixes

Run `38122504937`, source `9221689e0b637d4d0e4a63f54325a78190a1a533`, was cancelled after genuine Windows failures. Its Mac results are diagnostic only and were not substituted for the new source. A real annotation command-category regression caused by sidebar regrouping was fixed using canonical annotation tool IDs; the original command assertions remain unchanged. p3/p4 UI tests now share the real startup QApplication/style lifetime, addressing native Qt teardown/recreation crashes. Mac now includes p4/sidebar tests. General focused CI previously hit its 20-minute limit; release branches now retain source quality and use complete native gates without that duplicate execution. The 55-test ToolsPort module passed locally; its lengthy execution was not treated as a hang or bypassed.

## Distribution limits

- Windows x64: account-enabled Managed installer/portable; original v3.0.3 update route retained.
- Mac: Apple Silicon/macOS 13+, ad-hoc signed testing build, not Apple notarized. Intel and Mac OCR parity are outside this release.
- No printer/DFE real-machine claims are added.
- Template/workflow/barcode formats and the update trust key are unchanged.
- Current release state: Draft pending concrete operator evidence. Never fill pending gates from earlier-version tests.
