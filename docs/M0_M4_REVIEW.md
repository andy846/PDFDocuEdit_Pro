# M0 + M4 Consolidated Owner Review

## Scope and baseline

- Product worktree: `C:/Users/andy8/.codex/worktrees/print-composition-v3/PDFdocuEdit_Pro`.
- Branch: `codex/deep-search-restore-layout`; base HEAD `a5cd66db8d071c6db733c1f10e4f926751b83a76`.
- Release reference: v3.0.9, `95c839e13c39947e962fa4d47f5d584087614320`. The baseline differs only in release-validation documentation.
- This is one uncommitted M0/M4 review package. No new branch, main changes, merge, push, packaging, release, public version change, dependency or project-format change.
- M1/M2/M3/M5/M6 and the broader v3.1 programme remain deferred.

## 1. Implementation summary

### M0 — Command dispatch admission

`PDFViewer._run_command()` resolves the exact ID from the current mode's registry and reevaluates `Command.is_enabled()` immediately before invoking its handler. Missing or disabled commands are rejected with concise feedback. Registry/availability exceptions fail closed and use existing payload-free diagnostics; handler exceptions remain outside this boundary. No palette search, shortcut or registry redesign.

Generate PDF keeps its existing capability requirements: it can enter Production Review before formal authorization. No handler or authorization bypass was added.

### M4 — Read-only Production Review dashboard

The existing Summary tab now contains six compact metric cards, separate planned/final barcode stages, font findings, Issues links, paper/profile/settings source and output locations. Full checked-plan text remains expandable. Existing Mailpieces, Paper sheets, Barcode values and Issues views, paginated retrieval, warning acknowledgement and the fixed confirmation footer remain.

The immutable presentation model consumes existing summary/result dictionaries. Missing values remain unavailable; zero is only shown when supplied. Planned pages and generated pages are separate. Review checking/blocked/warnings/stale/cancelled, confirmation, generation, PDF publication and reports-only publication are distinct.

Output observation is limited to the worker created by the already-approved continuation. Snapshot ID, fingerprint and job ID must match; terminal results are displayed only after worker teardown. A new review, closed owner or mismatched result cannot borrow old success. No new worker is created for dashboard display.

Production progress changes runtime fields in batch/branch models. After confirmation, a presentation-only input view excludes known execution bookkeeping so switching dashboard jobs does not mistake ordinary progress for changed inputs. The original state hash still disables confirmation exactly as before. Actual template, source, prepared-data, selection or settings changes remain stale; the display projection never authorizes a job.

### Validation integrity

- Planned barcode validation does not imply final PDF decoding.
- Final coverage uses only counters from the same final result, not the planned-stage denominator. Partial/inconsistent/absent evidence remains Incomplete or Not Checked.
- Template Direct Content QR and other configurations without established full audit scope are not claimed as fully verified. Supported I25/fixed-profile targets and Overlay results use their existing final audit evidence.
- Zero decode counters alone never mean Passed. A complete no-barcode plan or a checked zero-page reports-only job can establish Not Applicable.
- Font counts use existing preflight/production scan counters; missing record/page coverage is explicit. Counts are not a layout-safety guarantee. Existing reports open through PlatformService; no CSV scan occurs on the GUI thread.
- Overlay's existing `report_dir/glyph-repairs.csv` location is projected without scanning files. Physical page mapping is not fabricated from template references.

### Scope deviations

None. Missing coverage/metrics are displayed as limitations rather than expanding the engine or changing production rules. One review package includes both milestones.

### Independent review

One fresh-context, read-only review found three P2 display/integration issues: batch/branch progress invalidating completion, reports-only publication being omitted, and the Overlay font-report link disappearing. All three were reproduced with failing tests and fixed in the same review pass. Additional missing-evidence guards were also verified RED → GREEN. No deferred minor findings were reported.

## 2. Files changed

| File | Change |
|---|---|
| `core/viewer.py` | Execution-time command admission and existing diagnostics/feedback. |
| `composition/review/presentation.py` | Immutable dashboard model, explicit unknown/stage/coverage states; existing next-step helper retained. |
| `composition/review/dashboard.py` (new) | Responsive read-only metric widgets and navigation signals using existing tokens/theme. |
| `composition/review/ui.py` | Summary integration, existing controller state projection and same-worker result observation; no production dispatch replacement. |
| `styles/components.py` | Three scoped card/value/status selectors in the existing stylesheet. |
| `scripts/ci_plan.py` | Register the two new GUI test modules in the existing UI test group. |
| `tests/test_command_dispatch_safety.py` (new) | Enabled/disabled/stale/missing/error dispatch, real palette activation and handler exception boundary. |
| `tests/composition/test_review_dashboard.py` (new) | Missing/zero, stages, barcode coverage, fonts, identity, reports-only and unconfirmed-output guards. |
| `tests/composition/test_review_dashboard_ui.py` (new) | Styled responsive UI, warnings/stale state, real Template generation, multiple jobs and worker lifecycle. |
| `tests/composition/test_workspace_modes.py` | Real viewer active-document/mode dispatch regression. |
| `tests/composition/test_pdf_overlay_ui.py` | Existing real Overlay generation also verifies dashboard counts/decode state. |
| `tests/test_workflow_production_review.py` | Existing batch/branch/PDF workflow output tests also verify matching dashboard results. |
| `README.md`, `dialogs/readme_dialog.py` | Unreleased feature description and limits; no version change. |
| `docs/M0_M4_REVIEW.md` (new) | This consolidated report. |

PDF engines, `review/service.py`, `review/authorization.py`, source/snapshot fingerprinting, physical sheet/duplex/media/barcode algorithms, reconciliation and atomic publication remain unchanged.

## 3. Test results

Verification is complete. Raw local evidence is under `build/probes/m0-m4/`; it is not product/customer data and is not intended for Git.

- TDD: M0 7 failures reproduced before dispatch fix → 14 passing tests with existing commands.
- M4 model/UI absence and result-edge failures were reproduced before implementation/fixes.
- Independent review findings: 3 failures/33 passes before fixes → 60 passes; strengthened report-only/Overlay integration → 67 passes.
- Final command/model/UI group after missing-evidence guards: 52 passed.
- Live viewer document switch plus shortcut review: 7 passed.

| Verification | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| Initial whole-suite isolated run, 190 modules / 2,661 collected | 2,654 | 3 | 0 | 4 |
| Affected-module rerun, 24 modules | 297 | 0 | 0 | 0 |
| Latest model/UI rerun, 2 modules | 38 | 0 | 0 | 0 |
| Latest evidence per module, 190 modules / 2,663 collected | **2,659** | **0** | **0** | **4** |

The initial whole-suite run started before the independent-review corrections were finished; its three failures are the reproduced dashboard findings, not hidden/filtered tests. The affected modules were rerun after correction, then the model/UI modules were rerun after the last reference-label/stale-latch changes. The last row uses the latest evidence for each module and counts each test once; it is **not** described as a single pristine whole-suite pass. Raw initial JUnit/logs remain intact. `verification-summary.json` maps every module to its retained run. Final-source SHA256s show no source changes after the final gates.

- Full-repository Ruff: passed (`All checks passed!`); `git diff --check`: passed.
- Final guarded command/model/UI/authorization group: 90 passed.
- Final isolated presentation modules: 38 passed (27 model, 11 UI).
- Final 200% Qt scale UI run: 11 passed.
- Final affected-module isolated rerun: 24 modules, 297 passed, 0 failed/errors/skips. These overlap the whole suite and are not added again to a unique test total.

## 4. Regression assessment

| Area | Assessment |
|---|---|
| Command handling / shortcuts | Exact current command ID and live admission; text-edit shortcut protection and existing registration remain. |
| PDF Viewer | One localized dispatch change; real document and mode-switch coverage added. |
| Production Review | Existing controller, workers, rows/preview services and fixed controls retained. |
| Barcode / media / duplex | Read-only counters and metadata only; generation/calculation code unchanged. |
| Authorization / output integrity | Existing rules, receipts, hashes, source integrity and atomic publication unchanged; dashboard cannot enable confirmation. |
| Lifecycle | No repaint worker or dataset duplication. Late observer callbacks require live owner/current review; existing cleanup retained. |

## 5. Performance

Windows offscreen, full product stylesheet and bundled font, 29 warm samples per variant:

| Probe | Baseline | M0/M4 |
|---|---:|---:|
| Review pane create/show median | 54.28 ms | 127.92 ms |
| Maximum observed sample | 74.35 ms | 155.76 ms |

The dashboard adds approximately 74 ms of fixed first-pane construction overhead in this synthetic probe. It is created on demand when review opens, not for every repaint or record. This is an observed cost, not a claim of zero performance impact.

A synthetic summary-only benchmark performed 10,000 model projections in approximately 0.13–0.20 s across the recorded probes; it did not read production records. The existing 10,000-record review/pagination test remains in the regression suite. Resize/repaint does not perform database queries, file scans or create workers. There is no extra full-document render or record widget collection.

Native startup latency, native user interaction/frame timing, peak memory on customer jobs and macOS performance have not been measured. Offscreen results do not prove native driver/window-system behavior.

## 6. UI and platform validation

| Environment | Status |
|---|---|
| Windows automated production/core/Qt tests | 190 modules exercised; latest per-module evidence 2,659 passed / 4 skipped / 0 remaining failures. |
| Windows offscreen light/dark, standard scale | Raster-inspected at 1280×820 and 960×640; fixed confirmation controls remain reachable. |
| Windows offscreen 200% scale | 11 UI tests passed; raster-inspected with `QT_SCALE_FACTOR=2`; narrow content scrolls, footer retained. |
| Smaller synthetic 480×320 request | Existing pane minimum can expand width; scrollable summary and footer retained. Supported acceptance target is 960×640. |
| Native interactive Windows | Not Tested in this task; owner review required. |
| macOS native / high DPI | Not Tested; no cross-platform success claim from Windows results. |

## 7. Limitations and decisions

- The dashboard reflects available local review/run evidence; it does not independently reopen PDFs or verify files on repaint.
- Results are transient to the active review/run, not a new persistent task/history subsystem.
- Direct Content QR/unknown audit scope may remain Incomplete despite successful decoding of supported targets.
- Missing font affected-record/physical-page metrics remain unavailable. Overlay reports count output-page scan entries, not unique mailpieces; this unit is explicit. No font algorithm or audit format was changed to manufacture metrics.
- Runtime status is excluded only from the consumed dashboard input projection; unknown input changes conservatively remain stale. Cost if that projection misses an unrecognized runtime field is stale display, never restored authorization.
- Four existing platform/capability tests are skipped on this host: three require native macOS bundle/Keychain/signing, one requires file-symlink permission. These are not claimed as tested.
- No first-class new task registry or notification center was introduced. Deferred v3.1 work remains deferred.

## 8. Final status

- M0: **Complete**.
- M4: **Complete**.
- Ready for Owner Review: **Yes**, with the native-platform limitations above.
- Delivery stops at owner review. No main merge, commit, push or release is authorized by this report.
