# Disposable events cannot block durable writes

Events are telemetry. Operational code may emit them, but nothing may
depend on their presence, their retention, or their successful delivery.
Three write paths violated that in the same shape: each committed a
durable fact and then treated the accompanying event's success as a
precondition for the fact itself.

- A DB-claim amendment rolled back when `DbClaimAmended` returned no id,
  so a severity filter or an events outage could withhold a validated
  operator decision that every gate reads off `items.db_mutation_profile`.
- A packet render returned before authoring any `path_context_values`
  row when the batch event produced no id, even though those rows are the
  authority the overlap classifier reads and their `recorded_event_id` is
  an opaque provenance string that never needed to be an event id.
- A terminal deployment event raised on a missing `event.ok`, so
  telemetry could surface as a pipeline error after `deployment_runs`
  already held the run's outcome.

Each now commits its own fact and records the event beside it. The render
batch mints its own operation id rather than borrowing one from telemetry.

## Why a savepoint rather than a bare try/except

Catching the emitter's exception is not enough on Postgres: a failed
statement aborts the whole transaction, so a swallowed event error still
takes the durable write down at commit time. `emit_bounded` runs the
emission inside a savepoint, which bounds a database-level failure to the
event alone and leaves the caller's transaction usable. Correlation stays
exact — the event still rides the same transaction when it succeeds.

A dropped event is logged with the reason and with a pointer to where the
durable fact lives, so an operator reading the log never has to guess
whether the work landed. A retired event name still raises: that is the
caller naming an event that no longer exists, not telemetry failing.

## Why board strategy volume moved off event byte counts

The board and Overview momentum surfaces derived per-day strategy
authoring from `new_bytes` / `old_bytes` on strategy-doc write events, so
historical work totals shrank as events aged out. `strategy_doc_revisions`
already stores every save's `byte_length` under a permanent content
contract, so both readers now share one measure computed from adjacent
saved revisions: each revision contributes the size it moved against the
one before it, and a document's first revision contributes its whole size.

The measure is deliberately bounded by what those revisions can show. It
is an approximate size change, not effort — a same-size rewrite reads as
zero. A document whose earliest saved revision is not revision 1 has no
knowable baseline, so that row is excluded rather than counted as if the
whole document had been authored that day; counting it would invent work
that a restored or imported corpus never did.
