# Deep Search responsiveness and Pause / Resume

Development baseline: v3.0.7, `4f841c9ad85acb1f6a2c9da59c657cf178f39b22`.
Public version, project formats and shared FunctionTask behaviour are unchanged.

## Behaviour

Pause requests a cooperative checkpoint; the current native PDF text extraction
or barcode decode finishes first. Resume retains the same iterator, open PDF,
keywords and results. Changing the query input does not change the paused run.
Cancel wakes a paused worker and retains only completed-file results.
This is an in-session pause, not restart recovery.

## Implementation boundaries

- `core/deep_search_runtime.py` owns one SQLite writer per search, Condition-based
  checkpoints and a coalesced mailbox. Search uses a dedicated one-thread pool,
  so a paused search does not occupy the shared rendering/export pool.
- `ui/search_queries.py` runs snapshot reads on separate owned connections.
  Headers/previews are coalesced; at most four page requests queue, latest first.
  Dropped requests clear model pending markers. Close waits for all owned work.
- `ui/search_hits_model.py` displays virtual result rows with 200-row pages and
  ten cached pages. A cutoff prevents mixed live snapshots; query generations
  and independent selection revisions reject stale results. Unloaded selections
  resolve their identity off-GUI before restoring their new sorted row.
- Deep Search polls progress every 100ms; visible Matches refresh at most every
  500ms and when the query service is idle. SQLite writes, counts, sorting and
  previews run off-GUI. File controls debounce 200ms; exports flush the latest
  filter input before capturing their scope.
- Narrow layouts wrap statuses and stack overflowing control rows. Existing
  WideComboBox provides screen-bounded, readable popups and selected tooltips.

The existing synchronous result model/store APIs remain for non-live consumers.
SearchFile/SearchHit contents, query rules and complete report exports are retained.

## Verification

Scoped command (66 passed):

```text
python -m pytest tests/test_deep_search.py tests/test_deep_search_detailed.py tests/test_deep_search_responsive.py tests/test_search_task_lifecycle.py tests/test_source_contract.py tests/test_ci_plan.py -q
```

Scoped Ruff and diff whitespace checks passed. Initial tests failed for missing
Pause/Resume and SQL running on the GUI thread. Additional regressions were seen
failing before fixing empty filters, mixed cutoffs, failed-search status,
selection restoration, page-queue bounds, latest-filter export, and clipped Pause
controls. No test was disabled. The old duplicate-search test now clears its
non-worker sentinel before close: this sentinel cannot signal finished; its
original duplicate-start assertion is unchanged.

Independent targeted review found the edge cases above; final selection review
reported no additional actionable defects. No full regression or packaging ran.

## Performance evidence and limits

Five Windows offscreen Qt runs used a generated 500-page text PDF with exactly
100,000 occurrences, with Matches visible and a 20ms event-loop heartbeat.
Results: generation/search wall time 1.581–1.616s; P95 heartbeat excess delay
1.75–2.53ms; maximum excess delay 8.57ms; zero worker warnings. The earlier direct
baseline measured a 123.98ms GUI result refresh and 55.11ms GUI final count; these
are different metrics, not a claimed end-to-end speedup factor.

Local probes and fixtures: `build/probes/deep-search-responsive/` (not committed).
The first probe exposed query binding errors; accepted evidence is
`result-accepted.json`, not earlier diagnostic runs. Customer PDFs, network
folders, image-heavy barcode decoding and macOS real-device responsiveness were
not benchmarked. Native calls and filesystem I/O cannot be interrupted mid-call.
Large file-summary tables remain the existing widget table; results append in
small batches. No unrelated UI overhaul, new public version or release.
