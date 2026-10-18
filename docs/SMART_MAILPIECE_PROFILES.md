# Smart Mailpiece / Customer Production Profiles

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
