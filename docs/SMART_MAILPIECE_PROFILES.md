# Smart Mailpiece / Customer Production Profiles

> Development moved to the canonical D: workspace on 2026-10-19; see [Development workspace](DEVELOPMENT_WORKSPACE.md). C: paths below identify the original implementation/QA baseline and remain historical evidence.

## Approved implementation contract

Baseline checkpoint: b9975ea on codex/deep-search-restore-layout (public 3.0.9).
Continue this worktree/branch only; no push, merge, release or public version bump.
M0 audit: reuse DetectionConfig v1/v2, SQLite PageIndex, EnvelopePlan/PrintPlan,
existing Overlay renderer, Production Review authorization, QC and atomic publishing.
Legacy .pdmp remains unchanged. New .pdmpx collections and .pdpp customer presets
contain declarative rules/layouts, never PageIndex text, source PDFs or old boundaries.
Unknown/ambiguous classifications must be resolved before accepting new-profile results.
Retain uniform geometry; per-type routing changes overlays only, not stock/tray/duplex
or sequence algorithms. Preserve legacy projects/fields; use overlay v9 only for new features.

## Milestones

M1: immutable profile revisions / CRUD / import-export / strict source-free schema.
M2: one-index multi-rule coordinator, primary signals, conflicts, cancellation.
M3: classification/index review, manual corrections, source binding and audited assets.
M4: integrate library/teaching/classification into existing Smart Detection UI.
M5: gated TemplateID Overlay selection, real output QC, regression and benchmarks.

Each milestone uses test-first changes, related tests and a separate verified commit.
Final deliverable includes synthetic 2k/8k benchmarks and owner UAT instructions.
macOS/physical printers/inserters require separate native acceptance; software decoding
alone never certifies machine compatibility.


## M0 architecture audit and risk assessment

The current approved product worktree is
`C:/Users/andy8/.codex/worktrees/print-composition-v3/PDFdocuEdit_Pro`,
branch `codex/deep-search-restore-layout`. Initial HEAD was `a5cd66d`;
previous verified, uncommitted product work was checkpointed separately as `b9975ea`.
The old D: checkout was not used for implementation. Public version remains 3.0.9.

- Existing DetectionConfig v1/v2, Analyze, Teach, spatial regions, identity labels,
  literal page-counter patterns and standalone `.pdmp` remain the detection foundation.
- `smart_detection.PageIndex` stores source text/positions in SQLite. It is a local,
  source-bound cache, never a reusable profile or exported production asset. Index
  identity includes source SHA256/stat/geometry and index version, not the rule set.
  One iterator now evaluates all rule sets; changing rules reuses extraction.
- The legacy `combine="any"` reducer can turn an isolated identity change or marker
  into a boundary. It remains unchanged for compatibility. Collections require an
  explicit marker or page restart as the primary; identity change alone is a finding.
- Terms within one marker remain AND. Alternative templates/heading alternatives
  belong in separate rule sets; two matches never silently choose the first type.
- Collections expose primary plus optional corroboration, or all configured signals
  required at a start. Missing required evidence blocks acceptance; a printed restart
  with no matching type becomes Unknown. Marker/counter contradictions remain findings.
- Without a marker or configured page counter, an unseen document type may not be
  detectable at all. A warning-free scan is not a correctness guarantee.
- Existing source inspection requires uniform MediaBox/CropBox/rotation for dynamic
  grouping. Mixed geometry is explicitly rejected, not normalized or rescaled.
- `EnvelopePlan` / `PrintPlan` remain authoritative for source/output pages, sequences,
  sheets and blank backs. TemplateID is contextual metadata, never a new counter.
- Designer and Visual Workflow share the same detection dialog and worker. Filtered
  Workflow production, inspection and Designer binding retain original envelope identity.
- Existing Production Review signatures, acknowledgement, source checks, barcode QC,
  reconciliation, claims/journal and atomic publication remain required. Accepting a
  detection review or importing a profile does not authorize output.

## Schemas and compatibility

| Artifact | Purpose | Bound |
|---|---|---|
| `.pdmp` | Existing single DetectionConfig profile | Existing 256 KiB limit unchanged |
| `.pdmpx` v1 | Source-free detection collection; up to 16 independent rule sets | 1 MiB; 300 library profiles; 1,000 revisions/profile |
| `.pdpp` v1 | Detection collection + existing overlay objects with TemplateID scopes | 5 MiB; 200 objects; font/image assets up to 100 MiB each |
| `.pdcx` overlay v9 | Classified source project / type-aware objects | Existing 10 MiB project read limit |
| `*.mailpieces.json` report v3 | Source-specific accepted classification, evidence and correction audit | 32 MiB, content-addressed and full SHA256 verified |

Legacy overlay versions 1–8 remain readable; legacy saves remain version 8 and omit
new empty object/profile fields. New classified/type-aware projects use overlay v9.
The reference release commit `95c839e` is an ancestor of initial `a5cd66d` (the local
`v3.0.9` tag was unavailable; no remote fetch was performed). Existing `.pdflow` schemas
are retained; referenced classification assets are copied
portably and checked. Old application versions cannot open the new v9 features.

A detection collection includes name, description, revision, stable rule/Template IDs,
static markers, spatial coordinates, patterns and signal settings. It excludes prior
source paths, customer records/text, cached index and accepted boundaries. `.pdpp`
exports configured layout content, Workflow field **names** (no values), and licensed
font/image assets. Applying to an existing Workflow requires matching declarations
and retains other current extraction fields. A standalone project with declared data
fields still requires the existing Workflow data provider for production. Use placeholders
for variable customer data and teach static features only. Transfer `.pdpp` with its
adjacent `.assets` folder when fonts/images are present.

Applying a customer preset replaces overlay objects and required read scope, clears
previous boundaries/acceptance, and uses one-page **pending preview** grouping until
scanning. It preserves sequence start/increment/format, media/tray and duplex settings.
The pending preview is not a production grouping and cannot generate output.

## Operator workflow

1. Open the source in PDF Envelope Overlay Designer and choose **Auto Detect Mailpieces**.
2. Use **Detection Profile Library…** to choose a saved profile, or Analyze/Teach a static
   feature in the existing PDF preview. Select representative first/continuation pages.
3. In the library create a named profile, **Add taught rule**, set a readable TemplateID,
   select the primary signal and verification mode. Repeat teaching for another type;
   use **Replace selected with taught rule** to revise a rule. Save a revision before Use.
   Name edits save a new revision; Duplicate creates a distinct profile identity.
4. Scan. Review type counts, page-count distribution and exceptions. Compare first/last
   and before/after pages. Unknown/ambiguous types and blocking conflicts require source
   inspection plus **Confirm type / boundaries…** (or split/merge correction) before acceptance.
5. Undo/Redo remains available. History is at most 20 edits, with a conservative 16 MiB
   estimate budget, retaining the latest reversible edit for large reports. No page text,
   page-index database or rendered image is copied into history.
6. **Export envelope index…** can export an unresolved draft. Export is not acceptance.
   **Accept & apply boundaries** independently verifies source bytes in the worker.
7. Set each overlay object's **Document type** to All or a TemplateID. Its ordinary
   first/front/last/letter-page scope still applies. Layers navigates to an applicable
   envelope. Barcode settings and samples use that same type context.
8. Save **Customer production profile…** as `.pdpp` to reuse detection rules and layouts.
   Open that profile on a new PDF, then scan and accept its new boundaries independently.
9. Use the existing Production Review. Acknowledgement and explicit production confirmation
   are still required; generation verifies source/classification assets and final barcodes.

## Audit reports

Existing `control.csv`, `envelopes.csv`, `pages.csv`, `barcodes.csv` and `detection.csv`
column meanings are unchanged. `detection.csv` now reads full evidence from the accepted
asset rather than treating an empty compact descriptor as evidence. New
`classifications.csv` provides EnvelopeIndex, EnvelopeSeq, StartPage, EndPage, PageCount,
TemplateID, MatchedRuleID, BoundaryEvidence, ReviewStatus, ProfileID, ProfileRevision and
SourceSHA256. `job.json.customer_production_profile` records the originating `.pdpp`
identity/name/revision. `job.json.mailpiece_classification` adds detection profile identity/revision,
source identity and operator correction audit. These are additive fields, not approval.

## Real eMPF UAT checklist (owner / production site)

- Use a representative **new** uniform-geometry eMPF PDF with known boundaries and several
  letter formats. Do not infer success from the synthetic fixtures below.
- Teach only static headings/labels. Save, rename, duplicate and export/import the profile;
  test reuse on a different month's PDF without retaining old source paths or boundaries.
- Verify exact ranges and types, especially repeated account IDs, continuation headings,
  page restarts, blank pages, unknown/ambiguous types, unusually long groups and PDF EOF.
- Correct exceptions, Undo/Redo, export the draft index and explicitly accept. Change the
  source/settings afterwards and confirm old review/authorization cannot be reused.
- Give two types distinct QR/I25 positions. Confirm previews, final locations, EnvelopeSeq,
  LetterPage/Count, global sheet progression, duplex padding and EOG with final reports.
- In Visual Workflow filter/reorder whole envelopes; check the first retained envelope
  keeps its original type/layout, not the type at its new ordinal.
- Run Production Review, acknowledge warnings and explicitly confirm. Compare every output
  part and QC index against the reference boundaries; verify source-page reconciliation.
- Proof print with actual tray/media settings and validate read position/direction/dimensions
  on the production inserter. Software decoding alone does not establish compatibility.

## Validation evidence

Detailed commands, counts, benchmarks, platform limits and final commit/status evidence
are recorded below after final regression. Local logs and fixtures remain under
`build/probes/smart-profile-upgrade/` and are not committed.


## Final review repairs

A single independent review found two important cases, both reproduced before repair:
(1) edited Workflow boundaries could shift an ordinal to another same-length type;
(2) successful ID extraction was mistaken for an error in all-signals mode. Remapping
now requires exact original-range proof from Workflow and blocks changed/missing proof;
Auto Detect can reopen with rules only and requires a new scan/acceptance. Valid IDs
use the error's truth value, with positive and negative regression coverage.
Workflow field declarations can also travel in `.pdpp` without any customer values.

The common Worker completion path now drains the entire final event file before
cleanup: a deterministic 3 MiB result test reproduced loss beyond its periodic 1 MiB
read. Periodic reads remain bounded; no new task-tracking architecture was introduced.
Classification assets use shorter content-addressed filenames for Windows deep paths,
while every integrity comparison still uses the full SHA256.

## Implementation inventory

All milestone implementation is local on the original approved branch. No remote
operations, installers, release, public version bump or additional worktree were used.

| Component | Meaningful changes |
|---|---|
| New `pdf_source/profile_library.py` | Strict source-free `.pdmpx`, legacy import, bounded immutable revision library |
| New `pdf_source/multi_detection.py` | Thin multi-rule resolver over shared PageIndex and existing signal interpretation |
| New `pdf_source/classification.py` | Source-bound classification, correction audit, accepted assets, draft CSV, original-range mapping |
| New `pdf_source/production_profiles.py` | Portable `.pdpp` detection/layout association and declared field names |
| Existing `pdf_source/smart_detection.py` | Shared signal helper; legacy reducer retained |
| New `designer/mailpiece_profile_library.py` | Profile management within existing detection workflow |
| Existing `designer/mailpiece_dialog.py`, `mailpiece_smart_ui.py`, `mailpiece_workflow.py` | Background profile scan/load/accept, exception/type review, Undo/Redo, shared Workflow host |
| Existing `designer/overlay_actions.py`, `overlay_files.py`, `overlay_usability.py`, `overlay_workspace.py` | Type scopes, customer profile actions, contextual samples and source replacement |
| Existing `designer/process.py` | Drain final worker events before cleanup; regression for large completion messages |
| Existing `overlay/model.py`, `renderer.py`, `generator.py` | v9 optional type scopes using existing page context and output engine |
| Existing `overlay/serializer.py`, `reports.py` | Portable accepted assets, additive classification report/provenance |
| Existing `review/service.py`, `composition/worker.py` | Include accepted classification resources in existing review/generation verification |
| Existing `workflow/engine.py`, `pdf_pipeline.py`, `inspection.py`, `worker.py`, `serializer.py` | Preserve original classified ranges/types through selection, preview and portable saves |
| `scripts/ci_plan.py` and tests | Register new Qt modules and exercise legacy/new detection, routing, output integrity and scale |

Paths in the table are relative to `composition/` except `workflow/`, `scripts/` and
tests. The complete file list is available with `git diff --name-only b9975ea HEAD`.
ProductionAuthorization implementation, PDF editing engine, media/duplex algorithms,
barcode generation architecture and public version were not changed by this feature.

## Measured performance (synthetic Windows fixtures)

These are simple text PDFs with known variable-length groups, not customer eMPF
files, image-heavy scans or estimates for arbitrary PDFs. Times include source
validation/index work in the worker. Each case ran in a fresh benchmark process.

| Pages / rule sets | Initial index + scan | Cached scan | Changed rules, same index | Maximum observed worker peak |
|---|---:|---:|---:|---:|
| 2,000 / 4 | 0.4090 s | 0.1910 s | 0.1978 s | 69.2 MiB |
| 8,000 / 4 | 1.7812 s | 0.8543 s | 0.8522 s | 80.9 MiB |
| 8,000 / 8 | 1.6091 s | 0.7929 s | 0.7730 s | 82.3 MiB |

The 8-rule run being faster than the 4-rule run is measurement noise, not a claimed
scaling improvement. SQLite was reused across rule changes (436 KiB / 1,700 KiB),
with no unfinished index files. Exact initial envelope ranges/types were asserted
(800 envelopes at 2k, 3,200 at 8k). Changed rule sets deliberately leave unknown groups.
Immediate cancellation measured 0.0010–0.0013 s; separate tests cancel mid-index and
mid-rule evaluation, verify cleanup/cache retention as appropriate and retry safely.

Actual Qt worker-path tests measured 2k initial/cached at 1.23/0.90 s and 8k at
3.45/2.18 s; a loaded run measured 8k at 5.66/3.43 s. Maximum observed timer heartbeat
gaps were 0.081–0.120 s; parent-process peak memory was approximately 141–171 MiB.
No per-page image collection or per-record widget grid was introduced. This is
observed responsiveness on synthetic data, not proof for every customer file.
An earlier combined scale process did not finish; its evidence was retained and it
was not counted as success. Fresh isolated and combined scale reruns passed.

## Scope limits and platform acceptance

- M0–M5 implementation is complete for uniform-geometry source PDFs and existing
  overlay object types. Template routing is supported and tested; per-type media,
  tray, duplex and a second sequence engine are intentionally absent.
- Existing single-profile detection, fixed grouping and legacy project formats remain
  supported. Old application versions do not understand new overlay v9 projects.
- Profiles store declarative settings only. User-authored static marker/layout text
  must itself avoid private values; the application cannot infer whether an arbitrary
  user-entered literal is a customer identifier. Production source text/records are
  never automatically copied into reusable profile metadata.
- Unconfigured/unknown formats can lack a detectable signal. Operator boundary/type
  review remains necessary; no numeric confidence score or automatic approval exists.
- Generic/QR and I25 output use their existing verification paths; passing software
  decode is not physical machine validation. Existing unsupported final decode coverage
  remains explicitly limited by those paths, not manufactured by profile support.
- Windows automated Qt offscreen tests: standard scale, light/dark, narrow windows and
  200% scale exercised. Native interactive Windows owner UAT: **Not Tested** this round.
- Actual customer files: **Not Tested** this round. macOS: **Not Tested**.
  Production printers/inserters/RIP: **Not Tested**. Packaging/installers: **Not Run**
  (out of scope; no dependencies added).
- Deferred: OCR/image markers, mixed geometry normalization, broad Designer redesign,
  media routing by type, physical machine certification and product release.

## Final QA and delivery status — 2026-10-19

| Gate | Passed | Failed | Skipped | Evidence |
|---|---:|---:|---:|---|
| Full regression, 209 fresh-process modules | 2,920 | 0 | 4 | `full-regression/result.json` |
| Final review repairs, latest results across 15 affected modules | 228 | 0 | 0 | `final-review-regression/` with 7 modules superseded by `final-proof-corrected/` |
| Consolidated latest result for each of the 209 modules | 2,926 | 0 | 4 | `latest-verified-results.json` |
| 200% Qt UI run | 14 | 0 | 0 | `final-high-dpi.xml` |
| Dedicated 2k/8k Qt worker/heartbeat run | 2 | 0 | 0 | `m5-scale-ui-final.xml` |

These rows overlap and **must not be added together**. The full regression started
before final review repairs; affected modules were rerun afterward. The consolidated
figure substitutes each affected module's latest result, preserving all original logs.
All evidence paths are relative to local `build/probes/smart-profile-upgrade/`.

Four environmental skips: macOS bundle symlink/permissions, Keychain, arm64 signed
install/rollback; one file-symlink publication check lacks host symlink permission.
No failing tests were removed or weakened. Test-first missing-feature assertions and
review bug reproductions initially failed as expected before repair. Two targeted
runner invocations used incorrect Workflow test paths; they ran no tests for those
paths, were retained as unsuccessful invocations, then corrected with all selected
modules passing. One earlier unfinished scale process is documented above.

Ruff over the repository, compileall for composition/workflow and `git diff --check`
passed. Existing commands/Viewer, Production Review authorization, legacy detection,
media/duplex, barcode/QC, bounded output and Visual Workflow regressions are included
in the full suite. No authorization module rules were changed. New end-to-end tests
generated actual synthetic PDF output and decoded QR/I25, including type routing,
sequence/sheet/EOG semantics, split publication and classification reports.

### Reproduction commands

Use the approved worktree and its existing verified Python environment (Python path:
`C:/Users/andy8/.codex/worktrees/supabase-private-login/PDFdocuEdit_Pro/.venv/Scripts/python.exe`).
The following commands assume that executable is called `python`:

```text
python -m scripts.regression_suite --group all --output build/probes/smart-profile-upgrade/full-regression
python -m ruff check .
python -m compileall -q composition workflow
git diff --check
```

The final affected regression used `scripts.regression_suite.run` with timeout 240,
separate subprocesses and the module list below. The first 15-module run was followed
by a seven-module proof-path rerun after adding the last same-snapshot regression:

```python
from pathlib import Path
from scripts.regression_suite import run
modules = ['tests/composition/test_detection_profile_library.py', 'tests/composition/test_multi_rule_detection.py', 'tests/composition/test_mailpiece_classification.py', 'tests/composition/test_mailpiece_profiles_ui.py', 'tests/composition/test_template_overlay_routing.py', 'tests/composition/test_smart_mailpiece_integration.py', 'tests/composition/test_pdf_overlay_models.py', 'tests/composition/test_pdf_overlay_engine.py', 'tests/test_workflow_core.py', 'tests/test_workflow_data_steps.py', 'tests/test_workflow_inspection.py', 'tests/test_workflow_inspection_ui.py', 'tests/test_workflow_media_settings.py', 'tests/test_workflow_production_review.py', 'tests/test_production_authorization.py']
raise SystemExit(run(modules, Path("build/probes/smart-profile-upgrade/owner-recheck"), timeout=240))
```

The additional high-DPI command was equivalent to PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_SCALE_FACTOR = "2"
python -m pytest -q tests/composition/test_mailpiece_profiles_ui.py --junitxml=build/probes/smart-profile-upgrade/final-high-dpi.xml
```

Scale and isolated benchmark reproduction:

```text
python -m pytest -q tests/composition/test_multi_profile_scale_ui.py --junitxml=build/probes/smart-profile-upgrade/m5-scale-ui-final.xml
python build/probes/smart-profile-upgrade/benchmark.py
```

The benchmark script/fixtures are local one-off probes, not maintained scripts or
committed customer material. The automated test module is maintained in the repository.

### Local checkpoints

| Commit | Purpose |
|---|---|
| `b9975ea` | Separate verified checkpoint of previous updates (91 files); not mixed into this feature |
| `aeb2377` | Detection profile library |
| `c3a91be` | Shared-index multi-rule resolution |
| `f195f70` | Source-bound classification and portable audit assets |
| `f71ad39` | Shared Designer / Workflow detection UI |
| `92aab99` | Customer production profiles and type-specific existing Overlay/QC |
| `47e35bb` | Final review provenance, valid-ID and field-declaration repairs |

A final documentation-only verification checkpoint records this report. All commits
remain on `codex/deep-search-restore-layout`; no main modification, branch creation,
remote push, merge, release, installer or public version change was performed.
Implementation working tree was clean at `47e35bb`; final report/HEAD and clean
working-tree status are recorded in the local delivery manifest after committing.

**Milestones M0, M1, M2, M3, M4 and M5: Implemented and automated-tested.**
**Ready for owner review and real eMPF UAT: Yes.**
This is readiness for owner acceptance, not customer-file or physical machine certification.


## Auto Detect window / direct profile saving — UAT follow-up 2026-10-19

Baseline: `bdb891f`, canonical D: worktree, same development branch. The reported
window started at only 880 x 650 and Profile actions scrolled with the configuration.
Drawing/capturing a region did not compile a spatial rule; Save required a prior
Try taught rule. Editing a lesson could also leave an older smart_config available.

The default is now bounded to 92% of the current available screen width and 90% of
height, capped at 1400 x 900 logical pixels, with a maximize control. Profile/Analyze/
Teach actions stay in one fixed top row; the bounded settings pane gives remaining
space to the source previews. Narrow 960 x 640 layouts and existing scroll controls
remain supported.

During teaching the first deliberate page drag captures the marker region; later
drags can still capture ID regions. Explicit Use marker region remains available.
Choose representative first/continuation pages and a short **static PDF text heading**.
Unknown headings must be entered explicitly to avoid persisting extracted customer
values. Save profile tests the current lesson in the existing worker, then opens the
file picker after successful completion. Try taught rule remains available for review.
Returning to boundary review does not discard a pending lesson. Editing the lesson
invalidates the prior rule; changing detection methods cannot export an obsolete rule.

Cancellation, failed teaching, a closed dialog or a superseded configuration cannot
continue the deferred Save. Missing-text/image/QR selections explain why no profile
was saved. **QR/image recognition is not supported by this text-layer detector.**
No extraction/detection algorithm, profile schema, source verification, boundary
acceptance or production authorization rule changed. Existing customer collection
exports and .pdmp compatibility remain intact.

Verification: 19 shared-dialog integration tests plus 103 tests across seven related
modules passed (122 total, no failures/skips). A separate four-case 200% layout run
passed. Existing narrow light/dark, new direct Save, edited/incorrect lesson, cancel,
return-to-review, blank/image area and stale-method cases are covered. Ruff, compileall,
source verification and whitespace checks passed. The full product suite was not
repeated for this UI follow-up; its earlier D-drive baseline is recorded separately.

Synthetic source previews were visually inspected in both themes using hidden native
Windows Qt windows at devicePixelRatio 2. Headless offscreen font rendering was not
used as evidence of native text appearance. The owner's open customer document/app
was not restarted or manipulated; save the project and restart through the D-drive
entry point to load the fix. No packaging, version change or publication occurred.
Local RED/GREEN, regression and visual evidence: `build/probes/mailpiece-dialog-save/`.


## Region/rule profiles — UAT correction 2026-10-19

The previous Save guard incorrectly limited standalone profiles to Auto/Teach v2.
A successful `region_present` scan uses the existing DetectionConfig v1 and was
therefore rejected by both the UI and the profile serializer. This was an incomplete
Save integration, not evidence that the selected region failed to group the PDF.

Save now validates and serializes the **currently selected method** using the same
`config()` path as Scan: region presence, page restart, identity change, static text,
separator and combined rules, as well as existing v2 spatial rules. A previous smart
rule/customer collection or unfinished teaching lesson cannot override a selected
manual method. Invalid rules are rejected before the file picker.

Standalone `.pdmp` retains `profile_version: 1` and the existing bounded declarative
config shape; config.version now accepts the already supported DetectionConfig 1
and 2 validators. Saving manual rules does not extract PDF text. Region-presence profiles
contain coordinates and rule options, not recipient text, PDF paths, accepted groups,
manual corrections, acknowledgement or production authorization. User-entered text
markers/patterns remain declarative settings: operators should use static labels.
Opening a profile restores its matching method and controls and invalidates previous
review; the new PDF must be scanned and independently accepted. Saving leaves the
current source-specific boundary review intact. Smart-only suggestion/failure text
is hidden for manually selected methods.

Older builds that only accept v2 profiles will reject the newly supported v1 `.pdmp`
configs; existing v2 profiles remain compatible. Multi-template `.pdmpx` collection
imports still require v2 spatial rules; use **Open profile** for standalone v1 files.
Malformed/overlong profile names are rejected before entering UI callbacks.
No multi-rule resolver, detection engine, profile wrapper version, project format,
production authorization or public application version changed.

Verification evidence is retained locally under
`build/probes/mailpiece-region-profile/`. The focused run covers actual synthetic
PDF scan → Save → Open → rescan with exact boundaries, current-method routing,
invalid-rule rejection, source-free saved data and the previous teaching regressions.
No customer PDF was read or modified for this fix. The running owner application
must be restarted after saving the project to load the corrected code.

Results: full isolated-module regression completed 211 modules: 2,947 passed,
4 skipped, zero failures/errors. The skips cover three native macOS cases
(symlink permissions, Keychain, arm64 signing/install) and one host file-symlink
permission case. The final source additionally passed all 62 tests across four
profile modules, including the two malformed-name cases added after the full run
started. No claim of native macOS validation is made. Ruff, source verification and
whitespace checks passed; native Windows dark/light synthetic previews were visually
inspected at 200% scaling. The owner application and customer file were untouched.


## Save / Detection Profile Library integration — 2026-10-19

This resolves the library limitation described in the preceding UAT correction.
The library is an operator-maintained catalogue: it does not learn, create entries,
or import files merely because a PDF was analyzed or scanned.

- Explicit **Save profile** keeps the chosen portable file and registers its rules
  in the same Detection Profile Library. This applies to standalone v1/v2 `.pdmp`
  and externally opened multi-template `.pdmpx` profiles.
- Existing region/text/page-counter/ID/separator/combined v1 files can be imported
  through the existing **Import .pdmp / .pdmpx** action. No directory-wide discovery,
  migration or automatic import is performed. Existing owner files remain in place.
- **Use saved profile** restores a standalone rule through the existing detection
  method/config controls, or a collection through the existing multi-rule route.
  It invalidates the current PDF review and never accepts boundaries or production.
- Save/registration uses the existing active worker lock. Opening Library before it
  finishes is rejected with a wait message. Library refresh runs after worker-end
  releases the owner lock, so newly imported/saved entries appear immediately.
- Portable-file success and catalogue-registration failure are reported separately.
  The saved file remains usable if the library is unavailable, full or has a revision
  conflict. Unexpected programming exceptions retain existing worker diagnostics.

### Storage and compatibility

The Windows library location is still the per-user application-data location,
normally `%LOCALAPPDATA%/PDFDocuEdit/PDFDocuEdit Pro/composition/mailpiece-profiles`.
The dialog displays its actual resolved root (including an explicit update-root
override when used). It remains independent of the source checkout / D-drive path.

Existing collection folders and `rNNNNNN.pdmpx` revisions are unchanged. Standalone
profiles use their own generated-identity folders with immutable `rNNNNNN.pdmp`
revisions. The existing portable `.pdmp` wrapper/config schema is retained; name is
stored in `config.profile_name`, while identity/revision are inferred from controlled
library folder/filenames. Runtime `single_mailpiece_detection` records are not a new
public project/profile format. Mixed collection/standalone revisions are rejected.

Single-rule and multi-template entries are labelled separately. Standalone name,
rename, duplicate, immutable revisions and export work in the existing editor.
Collection-only fields are hidden for standalone entries; edit their detection
settings by using the profile in the detection preview and saving again. Standalone
files retain their existing name/rules-only metadata (no new description field).
Saving an unchanged standalone config deduplicates identical entries. Saving an
edited selected profile with the same name adds a revision; choosing another file
name creates a separate entry. Collection imports retain the original revision/
identity and conflict protection. Multi-template v2 primary-signal requirements,
customer-production profile validation and production authorization are unchanged.

All library I/O remains in the existing worker. Lists transfer bounded metadata,
not page datasets. The 300-profile / 1,000-revision and existing file-size limits,
containment, malformed-profile rejection and atomic non-overwriting revision writes
remain enforced. Cancellation before a standalone revision write retains the prior
revision. No client PDF text, accepted boundaries or old source paths are added.

### Owner UAT

1. Save the current project before restarting the development app.
2. Open Auto Detect, choose an existing manual method (for example Text present in
   selected region), configure its region and scan a representative PDF.
3. Choose Save profile, select a portable filename, and wait for the Library success
   message. Saving must leave the current boundary review/acknowledgement intact.
4. Open Detection Profile Library. The new entry should be listed as Single rule,
   with the resolved library path visible. Select it and use it for a fresh scan.
5. To reuse an earlier portable file, use Import once; no manual file move is needed.
6. Rename/duplicate/export an entry, then switch between standalone and multi-template
   entries. Each new PDF must still be scanned, reviewed and explicitly accepted.

Local RED/GREEN, native Windows dark/light 200% visual evidence and full regression
results are retained under `build/probes/detection-library-integration/`. Only
synthetic fixtures were used; the owner's existing local profile was not read,
modified, moved or committed. No version bump, packaging, push or release occurred.

Verification completed: full regression, 211 isolated modules, 2,961
passed / 4 skipped / zero failures. The existing skips cover
native macOS symlink/Keychain/arm64 signing and host file-symlink permissions.
The final four affected profile modules passed 76 distinct
tests (the last catalogue run includes malformed standalone-file isolation). Full
regression began before the last UI/save-lock cases; final targeted results verify
those changes. Windows dark/light and 200% native screenshots were inspected;
macOS hardware was not tested. Ruff, source verification, compile and whitespace
checks passed. No claim of production-device or customer-file certification is made.
