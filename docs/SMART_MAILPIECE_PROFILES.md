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
Existing `.pdflow` schemas are retained; referenced classification assets are copied
portably and checked. Old application versions cannot open the new v9 features.

A detection collection includes name, description, revision, stable rule/Template IDs,
static markers, spatial coordinates, patterns and signal settings. It excludes prior
source paths, customer records/text, cached index and accepted boundaries. `.pdpp`
exports configured layout content and licensed font/image assets; use placeholders
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
SourceSHA256. `job.json.mailpiece_classification` adds detection profile identity/revision,
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
