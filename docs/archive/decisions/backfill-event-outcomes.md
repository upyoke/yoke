---
slug: backfill-event-outcomes
retired-without-apply: false
affected-tables:
  - events
related-helper: runtime.api.domain.migration_harness.record_audit_fingerprint
related-doctor-hc: HC-event-outcome-drift
---

# Decision: one-shot backfill of historical event-outcome drift

## Motivation

The pre-YOK-1761 emitters for `HarnessToolCallCompleted` stamped
`event_outcome='completed'` even when the underlying tool call carried
a nonzero `Exit code N` line in the response preview or a non-empty
top-level `error` field on the envelope. Downstream audit queries that
filter `event_outcome IN ('failed','denied','interrupted',
'structured_exit') OR exit_code > 0` therefore returned an artificially
small failure set; truth-of-the-ledger queries had to fall back to
substring grep against the envelope JSON to recover real failures.

YOK-1761 task 001 fixed the live emitters and introduced the
`runtime.api.domain.events_tool_call_outcome` classifier as the single
truth-table for the five-value outcome enum (`completed`, `failed`,
`denied`, `interrupted`, `structured_exit`). Tasks 002 and 003 wired
the orphan-sweep `interrupted` semantic and the dispatcher attribution.
This decision records the **fourth and final** corrective surface: a
one-shot historical backfill that rewrites `events` rows whose true
outcome is reconstructable from the envelope, paired with a doctor HC
(`HC-event-outcome-drift`) that surfaces residual drift the
conservative rewrite intentionally left untouched.

## Selection criteria — conservative by design

A row qualifies for rewrite only when **all** of the following hold:

1. `event_name = 'HarnessToolCallCompleted'` AND
   `event_outcome = 'completed'`.
2. `envelope._truncated` is **not** `true`. Truncated envelopes (>64 KB
   raw payload, stamped by `observe_event_emission.build_envelope`)
   have lost the preview text the classifier needs and CANNOT be
   reliably reclassified. They are left alone.
3. The reconstructed `EventRecord` carries one of the structured
   failure signals: a parseable `Exit code N` (with `N > 0`) in
   `envelope.context.detail.tool_response_preview` OR a non-empty
   `envelope.context.detail.error` string.
4. Passing that reconstructed record through
   `events_tool_call_outcome.classify_tool_call_outcome` returns a
   non-`completed` outcome (`failed`, `denied`, `interrupted`, or
   `structured_exit`). If the classifier returns `completed` despite
   the preview/error evidence, the row stays — the classifier is the
   single source of truth.

Rows that fail any of these are explicitly NOT rewritten and surface
through `HC-event-outcome-drift` as either a `skip_truncated` or
`skip_ambiguous` residual.

## Why the exception path

The backfill is a one-shot bulk-data correction against the
`events` table. Per `AGENTS.md` § *Governed DB Mutation*, ad-hoc bulk
writes to a declared authoritative DB are banned; the named exception
pattern is to route through
`runtime.api.domain.migration_harness.record_audit_fingerprint` with
an authored `exception_reason` and a paired decision record (this
file). The audit row created by `record_audit_fingerprint` carries:

- `migration_name = 'backfill_event_outcomes'`
- `model_name = 'primary'` (the authoritative Yoke install label)
- `backup_reason = 'event-outcome-backfill'` (creates a rollback
  backup of the DB before the rewrite commits)
- `exception_reason` = YOK-1761 justification string with this
  decision-record link inline.

## Cutover marker

After the rewrite commits and the audit row lands, the cutover timestamp
is recorded in the `data/config` key `event_outcome_drift_cutover_at`
(ISO-8601 UTC). The doctor HC treats this explicit marker as the
post-cutover boundary. A completed `migration_name='backfill_event_outcomes'`
audit row without the marker produces a WARN rather than a FAIL because
the audit row proves the data backfill ran, not that every running harness
is already using the fixed emitters. Once the marker exists,
post-cutover drift indicates a regression in the live emitters and FAILs
the HC; pre-cutover residual is informational and bounded by the
configurable tolerance `event_outcome_drift_pre_cutover_warn_max`
(default 10000).

## Cutover scope and deletion

This decision records a single one-shot apply. After the live apply
produces `migration_audit.state='completed'` on the Yoke
authoritative DB AND `HC-event-outcome-drift` PASSes (or WARNs only)
on the same DB, the cutover ticket (YOK-1761 task 4) deletes the
migration module and its module-only test in the same slice:

- `runtime/api/domain/migrations/backfill_event_outcomes.py`
- `runtime/api/domain/migrations/test_backfill_event_outcomes.py`

The doctor HC, its test, and this decision record remain as the
durable evidence that the cutover happened.
