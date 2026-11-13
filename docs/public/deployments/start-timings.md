# Deployment start timings

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Start timings
<!-- /yoke:breadcrumbs -->

Read the timing records a deploy driver and run creation write, and how to
measure a slow start from them. Timings are diagnostics: nothing operational
reads them, and a refused write never fails the run.

The driver raw capture contains `Deployment start timing: ` JSON lines from
preflight pin reading onward. Each step has a UTC start/end timestamp, monotonic
elapsed milliseconds, outcome, run ID, source SHA, member count, and transport.
Failed steps also record `reason_code`: the refusal's code when present,
otherwise the exception type, so a planned retry remains distinguishable from
a defect. SHA and member count remain unset until their authoritative reads.
Pin reading, worktree retirement/ensure, child launch, context substeps, branch
verification, QA seed, containment attestation, freeze, and executing stamp are
named separately. HTTPS returns server substeps with its response for the driver
to flush; local execution collects them through the same contract. The watcher
preserves preflight lines when it appends child output. Records carry no secrets
and are never operational authority.

Each run-scoped driver scope (preflight, watched child, pinned re-exec, pipeline)
also stores its start/end records in `deployment_run_timings` through
`deployment_runs.timings.record` when it closes; the pipeline also flushes at
each stage, so a running run's earlier steps are readable. Any machine can read
them:

```text
yoke deployment-runs timings RUN-ID [--json]
```

It prints per-step elapsed totals, then every record; `--json` returns each
record as the driver wrote it. A write that cannot land never fails the run: the
driver prints `Deployment timing record refused: ` with the run, the named error
and the recovery, the capture still holds the lines, and the next flush retries
them without duplicating any that landed. An empty answer names
that no timings were recorded.

For a start-gap measurement, subtract the earliest preflight-start timestamp
from the successful executing-transition end (both on the driver’s clock) in
that same run’s records. Report the sum of context elapsed time, freeze elapsed
time, and any refresh attempts alongside the total. Compare matched
source/transport/member-count conditions; missing markers are incomplete
evidence, never a zero-time result.

The read-only report computes it from the recorded timings:

```text
python3 -m yoke_core.tools.deployment_start_report --run-id RUN-ID --baseline-seconds SECONDS
```

The report refuses incomplete markers or more than one context build, and prints
the measured total and every step’s elapsed time; a slower start still reports
its measured difference.

Timing records distinguish `start_source_preparation`, `start_admission_reads`,
`start_item_run_locks`, `start_admission_recheck`, `start_source_refresh`,
`target_occupancy`, `composition_freeze`, `bound_source_provider`,
`bound_source_composition`, `bound_source_enrollment`, `bound_source_judgement`,
`bound_source_item_run_locks`, `bound_source_recheck`, `bound_source_commit`
and `executing_stamp`. The `start_admission_reads`, `bound_source_composition`,
`bound_source_enrollment` and `bound_source_judgement` steps read every member,
and judge the members enrollment would add, before the run row lock;
the two `_recheck` steps prove those reads current under it, and a changed
input repeats the reads while the lock is held. A lock timeout names the phase,
not an invented blocker; missing response/timing evidence stays unknown. Real-run verification must name
the exact deployed source and representative members; a small fixture is a
regression check, not proof of production startup time.

Fleet preparation reports the actual subphase under the declared deployment
stage: declarations, receipt authority, admin connection, roster, ownership,
extensions, copy dump/restore, boot convergence, invariants, product readers,
cleanup and receipt writing. Long subphases emit `phase=running`,
`outcome=pending` and elapsed milliseconds every thirty seconds. Restored-copy
reader diagnostics identify sessions, frontier, board, launch pages/details,
message attempts and items, with `record_count` and `completed_count` for each
record family. Every copied record still reaches its existing handler or
decoder. Bounded batches reuse the canonical session projection and item text
expressions, and fetch launch and attempt rows in sets; no check is sampled or
skipped. Batch data is discarded on exit and cannot cross copy authorities.
Connections opened under a bound copy still physically close.
Every timing line stays in the driver raw capture, which is where preparation
is identified before any provider dispatch. Outcome-only watchers do not
forward each line on its own: ordinary lines join the progress digest, at
most one digest line per flush window, which `yoke watch tail` holds until the
next urgent line or sentinel rather than waking on it; a line whose outcome is
failed is urgent and is forwarded immediately. Other watchers still emit timing lines
as they arrive. They carry run/source identity when supplied and no DSNs.
A missing end marker is unfinished evidence, never a successful receipt.

Creation uses the same timing format for `create_source`,
`create_provisional_composition`, `create_lock`, `create_locked_composition`,
`create_takeover`, `create_validation`, `enrollment_members`,
`create_commit`, `create_takeover_settlement` and
`create_response`. Source refresh attempts have their own marker. Long phases
emit the same thirty-second pending heartbeat; member validation also reports
record/completed counts. The creation handler collects these diagnostics and returns them in
`start_timings` on both local and HTTPS transports. The CLI saves the timing
records to complete private evidence and prints its path beside the compact
creation receipt; it does not repeat the records as an inline table. Deployment
execution keeps its streamed driver timings. Nested phase durations overlap
and must not be added as independent wall time. A missing response or end marker
does not authorize another create; keep the request's idempotency key and
reconcile the existing attempt.

Validation reads member workflow pins and skipped-candidate status in sets,
interprets each distinct pinned workflow version once per set, and resolves
refusal and rework labels together. Mutable statuses are read again on the
locked pass; no validation result survives provisional rollback.
The nested steps `validation_bound_sources`, `validation_custody`,
`validation_carried_work`, `validation_enrollment_plan` and
`validation_judgement` show where validation spends its time.

## Related

- [Start diagnostics](start-diagnostics.md)
- [Stage receipts](model/stage-receipts.md#table-deployment_run_timings)
