# Prune disposable universe records

```text
yoke universe retention get
yoke universe prune --dry-run
```

Connect to the intended universe first (`yoke env list`). Both operations
require its organization administrator. The reply names the universe,
effective settings, policy digest and fixed UTC cutoff. One invocation covers
all projects in that connected universe; it never discovers other tenants.

Preview is the default when no mode is supplied. It uses the deletion rules
without changing settings, data or owner lifecycles. Eligible counts stop at
a bounded cohort and say when more may exist. Protected counts are bounded
samples, never full-table totals; an unknown count is never reported as zero.

After reviewing the preview, an authorized administrator may run:

```text
yoke universe prune --apply
```

One invocation runs in the foreground until a full cycle over every table
deletes nothing. It fixes one UTC cutoff when it starts; records that cross
their retention age during the run wait for the next invocation, so the run
always ends. It commits bounded transactions, up to 5,000 physical rows for
scalar records and other child/parent graphs, and keeps deleting from a table
while more eligible rows remain. Each inventory snapshot transaction deletes
one complete eligible inventory, even when its children exceed 5,000 rows.

Short internal passes normally target eight seconds; the policy caps a pass
at twenty seconds, each statement at ten seconds or its remaining budget, and
locks at one second. When a pass reaches its budget, the next pass resumes
the same table; that is never a failure. A table that reaches its own
statement or lock limit with a full pass budget is skipped while the other
tables continue; it is retried up to three times per invocation and then
listed as not finished.

Output stays short. About every 10 seconds the command prints one progress
line: rows deleted so far, the largest table still being pruned, and elapsed
time. The final summary gives the total deleted, deletions for each table
that changed, the duration, and each table not finished with its reason and
recovery. `--full` adds per-table eligible, deleted and protected detail and
the policy digest; `--json` returns the complete result. Preview runs one
cycle and lists eligible counts.

There is no overall invocation timeout, timer, background worker, saved run,
resume/status command or retention editor. Command options cannot override
the effective policy. Ctrl-C keeps committed batches and prints the same
summary. Rerun the command to find remaining eligible records. A lost pass
reply means its outcome/count is unknown: output separates earlier
acknowledged totals and never resends that mutating pass automatically.

## Settings and defaults

The existing `universe_settings` store may hold one versioned `retention`
document; existing values are preserved. Boot, reads and prune passes never
seed retention settings. An absent document resolves
the shipped defaults read-only. Invalid settings refuse as
`retention_policy_invalid`; ask the universe administrator to restore a valid
document. A policy change during the command stops with
`retention_policy_changed`; review the effective settings and rerun.

| Disposable category | Default retention |
|---|---|
| Events by severity | DEBUG 1 day; INFO 30; WARN 90; ERROR 180; FATAL and STATUS 365 |
| YokeFunctionCalled, HookDispatchTelemetry, HarnessToolCallStarted, HarnessToolCallCompleted | 7 days |
| Successful token verification and allowed function authorization checks | 7 days |
| Other verification/authorization outcomes | 90 days |
| Credential issuance, revocation and other lifecycle audit | 365 days |
| Function replay ledger | 7 days; preserve the supported replay guarantee and in-flight requests |
| Completed/rejected workflow dispatch intents | 30 days after terminal update |
| Completed tool-call detail | 7 days after completion, with live-reference protection |
| Demonstrably settled, unreferenced agent-only message graphs | 30 days after final relevant settlement |
| Unreferenced succeeded/cancelled launch graphs | 30 days after completion/settlement |
| Terminal completed evidence-fetch detail | 7 days |
| Completed successful reaps and notified/owner-settled waits | 30 days |
| Remaining expired sign-in links, device codes, web sessions, attribution redemptions and merge locks | Eligible for manual cleanup 1 day after expiry |
| Remaining finished admission windows | Eligible for manual cleanup 1 day after the window |
| Unfinished snapshot uploads | Maximum 7 days from creation |

Protection wins over age. Event-name overrides precede severity windows;
unknown severities stay protected. Boundaries use strictly older-than UTC
elapsed days, including fractional-second precision. Security validity,
authorization, request identity and rate-limit decisions use their existing
owners. Existing faster cleanup continues at its original boundaries and cadence,
including immediate expired-session and device-code cleanup. The one-day cutoff
selects remaining old rows; it never creates a minimum hold, delays existing
cleanup, extends validity or resets a live budget.

## What stays protected

Human-sent or human-received messages, their body, identities and recipient
records remain forever. Direct CLI/dashboard origins and any human recipient
are protected; an agent session's human owner alone does not prove human
authorship. Legacy or uncertain origins remain protected. Pending, injected,
unread/actionable, leased, referenced or live-held message graphs stay.
Failed, expired and outcome-unknown launches remain actionable until their
lifecycle owner resolves them. An unresolved tool call is never age-pruned.

Snapshots retain each project's latest header and latest content-bearing
inventory, the latest path generations' last sightings, active lane heads,
nonterminal claim bases, and running/open-failure integrity references.
Protected inventories remain whole. Other history has no age or count floor.
Pruning never locks whole message or reference tables. Each cohort locks
only its own rows, skipping rows another writer holds, and the `DELETE`
rechecks protection before committing child-first deletion; a graph whose
parent stopped qualifying rolls back whole. Inventory snapshots keep one
table lock on the snapshot tables, which message writers never touch. Each
eligible inventory is deleted in one atomic transaction under the same time
and lock bounds. Other graphs exceeding
the physical row cap stay protected with their reason; no graph is partially thinned.

Temporary upload cleanup shares custody with begin/append/finalize/abort,
including internal commits and separate materialization. Expired or missing
staging refuses as `snapshot_upload_expired_or_missing`: restart snapshot sync
with a fresh upload. A busy upload is retained; finish its active operation
before retrying. Existing snapshot-base mismatch recovery performs a full
upload when an incremental base is no longer available.

All strategy revisions and bodies, Doctor history, durable item/claim/decision/
deployment/QA proof, credentials, current settings and maintenance audit history
remain untouched. Only explicitly supported disposable tables are eligible;
unknown and unrelated tables are left alone without blocking cleanup.

## Failures and storage

A table that keeps reaching its statement or lock limit appears under
"Not finished" with `retention_table_limit`, its reason and recovery: rerun
when the table is quieter, and ask the universe administrator to inspect its
indexes and locks if it repeats. Another database refusal stops the command
with `retention_table_failed` and the affected table; the failed transaction
rolls back and earlier committed counts remain. Restore the named connection
or table condition and rerun. The command never performs an unbounded scan to
force progress.

Results live in command output only. Pruning is a narrow exception to
maintenance audit persistence: it writes no prune
audit, receipt, progress, event or file record. Ordinary dispatcher telemetry
may occur, but cleanup does not depend on it and no prune result is ledgered.
Existing audit history remains unchanged.

No vacuum or analyze runs. PostgreSQL autovacuum owns space reuse; deletion
does not promise smaller files, reduced allocated storage, lower costs or a
particular savings total.
