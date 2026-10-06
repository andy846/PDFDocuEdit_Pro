# Mail Merge v5: implementation note

## Architecture review (M0)

The current `WorkflowSpec` and its canvas assume one outgoing connection per
node; `batch.prepare` pairs exactly one template and one input per job. Reusing
`spec.node(kind)` for a branched graph would select the wrong template. The v5
graph therefore has its own validator/compiler and worker operations. v1–v4
continue to use their current engine and inspection operations unchanged.

The new graph is a bounded For-each source, one common preparation chain, one
batch sequence, one exclusive route node, linear template branches, an exception
sink and a results collector. Named ports are represented by v5 edges containing
`source`, `target`, `port`. Cycles and nested routing are rejected. Runtime
identity is source item + branch + node; original record identities remain in a
SQLite reconciliation ledger. The UI reads 50 rows at a time.

Partitions are streamed to workspace-only CSV files for reuse of the existing
headless batch snapshot/check/generate APIs. Templates are copied into the
workspace with imported record mode; customer templates are never edited. No
rendering engine depends on Qt. A branch job is checked and explicitly approved
before generation. Normal records may be approved only after acknowledging the
exception and blocked-source summary. Completed valid jobs are retained during
retry; no automatic background resume or publication is introduced.

Global record sequence follows the ordered source list and each source's filtered
and sorted records. Exception rows reserve their sequence. Changing common
settings/sources invalidates the sequence; branch template/media settings
invalidate affected jobs. No printer access or new dependencies are needed.

Milestones: M1 graph/data contracts; M2 headless routing/reconciliation; M3
workspace/data input; M4 inspection/approval/production; M5 targeted scale/UI and
regression checks. This maps the requested M0–M4 product stages into reviewable
commits. Full packaging/public release is deferred until the user requests it.
