# PyMuPDF 2.0 compatibility and adoption review

## Scope and baseline

This is an engine compatibility assessment, not a released dependency upgrade.
The supported application dependency and daily `.venv-dev` remain **1.26.6**.
Do not install 2.0 into the daily environment or publish these QA candidates.

- Assessment started: 2026-10-22; completed: 2026-10-23.
- Source baseline: local `main`, `a0487dee17de7ce9693b667106c03c0bd43100ba`.
- Application version: 3.1.0, unchanged.
- Work stays in the existing D-drive checkout. No branch, worktree, remote
  synchronization, installer, or release is part of this assessment.
- The pre-existing untracked `BOCHK.pdmp` is excluded and was not inspected.
- Earlier `build/probes/pymupdf2/` material is retained as diagnostic evidence;
  its mixed installation and incomplete logs are not final acceptance evidence.

## Implemented preparation

1. `core/pdf_backend.py` exports the existing `fitz` alias from `pymupdf`.
   Application, worker, QA, and test imports use this shared headless adapter.
   The `core` package itself remains lazy. No new extraction pipeline is added.
2. Under 2.0 the adapter disables Layout and restores the 1.26.6 native quad
   correction default. Native text, geometry, rendering and production services
   retain their existing APIs and rules.
3. `main.py` initializes the native backend before Qt, **after** existing worker
   admission checks. Standalone QA tools establish their project path first and
   initialize the backend before Qt. Windows 2.0 embedding in the reverse order
   is explicitly rejected before the unsafe native import.
4. AcroForm enumeration resolves bounded parent chains and inherited action
   dictionaries. Existing restricted calculations and acknowledgement of scripts
   remain effective when 2.0 separates logical fields from page widgets.
   Updating a field preserves inherited script metadata. No arbitrary JavaScript
   execution or signature editing is added.
5. Tests check inherited calculations across save/reopen, acknowledgement without
   mutation, non-JavaScript actions, native settings, and real subprocess entry
   points. Font assertions compare actual embedded glyph outlines with the
   selected bundled font, allowing official full-face/PostScript name variants.
6. A PyInstaller data hook retains native libraries, distribution metadata and
   official 2.0 dependencies/resources. **This hook does not solve the frozen
   startup and build blockers below.** It is compatibility preparation only.

Most modified files contain import substitutions and import ordering changes.
The local `non-import-changes.json` records an AST-based check of the exceptions;
the check deliberately ignores import nodes and is not a behavioral proof.

## Confirmed compatibility findings

### Forms

The original candidate lost inherited calculation/action information when reading
`Widget.script_*`. Four original form tests failed on 2.0. Genuine parent-field
fixtures also reproduced missing calculations and missing script warnings on the
baseline. The shared fix reads the PDF field hierarchy and preserves actions
when updating appearances. It does not relax calculation or production policy.

### Text geometry and font metadata

Importing the 2.0 structured-extraction stack changes a process-wide quad setting;
the adapter restores the established native setting explicitly. Layout is off.

2.0 writes full face names where 1.26.6 writes PostScript names. The same generated
Latin/CJK fixture produced identical embedded font subset SHA-256 values and
identical rendered pixel SHA-256 values under both versions. Tests were changed
to check font names from actual font metadata and the actual rendered glyph
outlines, not a prefix of the display name. Rendering assertions were preserved.
This comparison is evidence for the synthetic fixture, not every customer PDF.

The native stamp reference API also changed: 2.0's `set_rotation(30); update()`
leaves the appearance matrix unrotated. The application's existing vector
appearance edit produces exactly the same pixels under both engines. A fixed
independent 1.26.6 reference PDF is retained under `tests/fixtures/`, with its
provenance and checksum. The existing four page-rotation tests compare against
that reference with the original pixel tolerance.

The full visual suite then found three genuine quarter-turn insertion failures
on 2.0. Native insertion now uses the existing vector appearance helper for that
runtime, compensating the page rotation once. The supported 1.26.6 native rotation
path is preserved, including its metadata/update behavior. No raster fallback or
new geometry engine is introduced. Both engines reran the complete Stamp/image,
annotation, transaction and rotated-bound tests.

### Windows native initialization: source workaround, frozen blocker

In the clean official 2.0 installation, importing QtCore before PyMuPDF reproduced
a native access violation (exit 3221225477) while importing ONNX Runtime. Loading
the PDF backend first works in source processes. A Python exception handler cannot
recover an access violation; the adapter rejects unsupported initialization order.

The current PyInstaller 6.14.2 Windows dependency-analysis subprocess imports Qt
packages before `pdf2docx`, which imports PyMuPDF. The candidate build crashed in
that subprocess. Separately, PyInstaller's standard Qt runtime hook imports
QtCore before application `main.py`, so the source bootstrap alone cannot certify
a frozen 2.0 application even if analysis succeeds.

**2.0 frozen deployment is blocked.** No PyInstaller monkeypatch, stripped
dependency install, or unverified early authentication/runtime hook is used to
claim success. Resolve the native/toolchain ordering with an independently
verified build/runtime strategy before reconsidering promotion.

### Official dependency cost

Disabling Layout after importing 2.0 does not avoid its import-time dependencies
or ONNX initialization. The candidate uses the complete official dependency set,
not `--no-deps`. Installation and `pip check` evidence are retained. Public
requirements and project dependency pins still specify 1.26.6.

The existing PDF-to-Word path was exercised with the real pinned pdf2docx 0.5.8
converter, not a mock. Both versions preserve the synthetic text and source PDF
and remove the temporary DOCX. On 2.0, pdf2docx emits a deprecation warning for its
own `fitz` import. That warning is retained; third-party code is not rewritten.
This source conversion result does not resolve the frozen DLL-analysis crash.

Upstream references: [2.0 changes](https://pymupdf.readthedocs.io/en/latest/changes.html),
[installation](https://pymupdf.readthedocs.io/en/latest/installation.html),
[Layout and extraction](https://pymupdf.readthedocs.io/en/latest/rag.html).
The native failure and packaging conclusions above come from local execution,
not an upstream claim that this application is compatible.

## Reproduction and evidence

All local generated evidence is retained under
`build/probes/pymupdf2-upgrade-20261022/` (ignored by Git). No customer PDFs or
account credentials are used. Logs may contain machine paths but no document
content from customer files.

Both environments use Windows x64 Python 3.12, PyQt6, PyInstaller 6.14.2 and
pyinstaller-hooks-contrib 2026.8. The candidate is a separate clean venv using
official PyMuPDF 2.0 and its full dependencies. `candidate-lock-final.txt` records
the resolved QA dependencies, including existing optional auth-test libraries;
those libraries are not a new application requirement.

PowerShell environment for these commands:

```powershell
$env:PYTHONUTF8 = '1'
$env:TEMP = "$PWD/build/probes/p2-tmp"
$env:TMP = $env:TEMP
$env:QT_QPA_PLATFORM = 'offscreen'
```

Full test commands (each module runs in a fresh process):

```powershell
.venv-dev/Scripts/python.exe -m scripts.regression_suite --group all --output build/probes/pymupdf2-upgrade-20261022/baseline-full
build/probes/pymupdf2-upgrade-20261022/candidate/Scripts/python.exe -m scripts.regression_suite --group all --output build/probes/pymupdf2-upgrade-20261022/candidate-full
```

Original failure logs are kept. Separate `baseline-rechecks` and
`candidate-rechecks` rerun every affected module in full. The initial baseline
Qt teardown crash in `test_rotated_page_edges.py` was reproduced; registering that
UI module with the existing shared QApplication lifecycle fixes the QA fixture.
The independent review also reproduced and fixed standalone QA bootstrap order
and direct-script project-path regressions, with RED-to-GREEN subprocess tests.

Sandbox runs also deny Windows process-tree termination and Credential Manager
cleanup. The complete PostScript-open module plus the exact affected native
credential test were rerun outside the sandbox, using only owned child processes
and a randomly named QA credential: **15 passed on each engine**. This is local
credential-storage verification, not a real account login acceptance. Original
sandbox failures remain retained and are not converted into skips.

```powershell
# Run in the native Windows QA context; substitute the candidate interpreter
# for the second engine. No real account is used.
.venv-dev/Scripts/python.exe -m pytest -q tests/test_postscript_open.py tests/test_private_auth.py::test_actual_windows_credential_manager_roundtrip
```

Frozen QA build commands use the existing full application spec, explicit
`PDFDOCUEDIT_BUILD_AUTH=0` and `PDFDOCUEDIT_ENABLE_COMPOSITION=1`, separate
`--distpath`/`--workpath` directories, and identical build-tool versions. This
does not produce an installer or a signed/published update. The baseline builds;
the candidate fails during DLL analysis as described above.

The baseline frozen Composition smoke reaches Designer and renders light/dark
and narrow screenshots, but fails at production output confirmation
(`composition_smoke.py`'s `last_output` check) and exits abnormally. The harness calls `start_production`, which now enters
Production Review and does not itself authorize output. It is **not**
a successful frozen production acceptance result. Its log and failure traceback
are retained. Existing production authorization is not bypassed to make the
legacy QA harness pass.

## Test and measurement results

Final numerical results and their scope are recorded below.

<!-- FINAL_RESULTS -->
The consolidated result (full runs plus complete affected-module reruns and the
explicit native Windows rechecks) is **3,558 passed, 0 failed, 6 skipped per
engine**, covering 3,564 distinct tests. This is not a claim that the original
uninterrupted runs were green.

| Evidence | 1.26.6 | 2.0 |
|---|---:|---:|
| Initial full run | 3,537 passed, 2 failed, 6 skipped; one module crashed before JUnit | 3,544 passed, 13 failed, 6 skipped |
| Consolidated final source results | 3,558 passed, 0 failed, 6 skipped | 3,558 passed, 0 failed, 6 skipped |
| Complete affected-module reruns | 11 modules passed | 11 modules passed |
| Annotation/Stamp/transaction/rotated-bound follow-up | 173 passed | 173 passed |
| Final guarded Stamp/image visual suite | 74 passed | 74 passed |
| Native Windows process/credential recheck | 15 passed | 15 passed |

Initial baseline counts exclude the 15-test module whose teardown crashed; its
complete rerun is included in the consolidated total. Later backend entrypoint
and real DOCX tests bring that module to eight tests. No failed test was removed
or converted into a skip. Six skips on each engine are three native macOS cases
and three symlink/junction permission cases; exact names/reasons are retained
in the full-suite JUnit and skip JSON files.

**Five-run medians on the same generated files (40 fresh processes):**

| Pages | Metric | 1.26.6 | 2.0 | Change | Gate |
|---:|---|---:|---:|---:|---|
| 2,000 | First rendered page (s) | 1.856 | 3.132 | +68.7% | Fail |
| 2,000 | GUI peak MiB | 139.000 | 170.695 | +22.8% | Fail |
| 2,000 | All-page text (s) | 0.218 | 0.221 | +1.5% | Pass |
| 2,000 | All-page thumbnails (s) | 0.183 | 0.225 | +22.8% | Fail |
| 2,000 | Editor backup snapshot (s) | 0.166 | 0.191 | +14.9% | Fail |
| 2,000 | Core peak MiB | 54.383 | 127.645 | +134.7% | Fail |
| 8,000 | First rendered page (s) | 1.849 | 2.821 | +52.5% | Fail |
| 8,000 | GUI peak MiB | 144.262 | 175.527 | +21.7% | Fail |
| 8,000 | All-page text (s) | 0.935 | 0.986 | +5.4% | Pass |
| 8,000 | All-page thumbnails (s) | 0.837 | 1.043 | +24.6% | Fail |
| 8,000 | Editor backup snapshot (s) | 0.821 | 1.111 | +35.2% | Fail |
| 8,000 | Core peak MiB | 73.379 | 146.504 | +99.7% | Fail |

The startup, thumbnail, Editor snapshot and peak-memory gates fail. Text
extraction passes the 10% regression gate on these fixtures. Turning Layout off
does not eliminate the additional import/memory cost. Do not generalize these
results into a speed claim for customer files.

The 1.26.6 full QA build contains 815,350,181 uncompressed bytes and compresses
to 352,213,650 bytes (335.90 MiB; ZIP deflate level 9). ZIP SHA-256:
`62be0a61f556cc344134c8a382bfb38a842fcf8ca1320c2626595b0fcc1d55db`.
There is no successful 2.0 frozen bundle: the package-size delta and frozen
acceptance gates are **Blocked**, not passed. The QA ZIP is neither signed nor
published.

**Benchmark correction and retained diagnostic:** The first core probe called
`tobytes(garbage=4, deflate=True)` and mislabeled it as a snapshot. That is a
compressed deduplicated rewrite, not the actual Editor backup. Its raw files and
the 180-second baseline 8,000-page timeout remain retained. All 20 formal core
trials were rerun using the actual product flags
`garbage=0, deflate=False, clean=False, no_new_id=True`; the 20 unaffected GUI
trials were retained against identical SHA-256-verified inputs. The formal table
above uses only those correct operation settings. Do not cite the diagnostic
rewrite timings as Undo improvement.
<!-- END_FINAL_RESULTS -->

The benchmark uses five fresh processes per version, size and operation group,
with the same generated 2,000/8,000-page text/vector PDFs. Filesystem caches are
not forcibly flushed. First-page timing includes backend import, Qt/editor
construction, synchronous document open and actual first rendered pixels, but
not OS process creation. Other timings measure all-page text extraction,
thumbnail rendering and a validated full-document backup using the exact
Editor snapshot settings. Peak memory is the
Windows process high-water working set. These results do not measure PS speed,
physical printer throughput, scanned/image-heavy customer PDFs, or inserters.

Adoption gates: operations at most 10% slower; first-page startup increase at most
the greater of 10% or 200 ms; peak RSS at most 20% higher; compressed Windows
package increase at most the greater of 10% or 25 MiB. A missing or blocked
measurement is not a pass. Both Windows and macOS readiness are required unless
the owner explicitly approves a separate platform scope.

## Platform and production limits

- Windows source regression and generated fixtures: see numerical results.
- Windows frozen 2.0: blocked; package-size delta unavailable.
- macOS source, packaging, DPI and native dependency compatibility: **Not Tested**.
- Actual customer files, private login, physical printing/RIP/inserter: **Not Tested**
  for this dependency candidate. Prior version acceptance does not transfer.
- Offscreen UI tests do not establish real display/high-DPI visual acceptance.
- No OCR, AI/Layout, detection rules, barcode algorithm, project format or public
  version changes are introduced.

## Decision and remaining work

Retain PyMuPDF **1.26.6** as the supported dependency. Source compatibility
preparation is reviewable, but 2.0 adoption is **not approved or complete**.
Resolve the Windows native/frozen blockers, investigate any performance gate
failures, repair and run the complete frozen acceptance flow, and obtain macOS
evidence before a separate dependency-promotion decision. Do not weaken
production checks, remove required official resources, or infer success from
source-only tests.
