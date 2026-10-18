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
