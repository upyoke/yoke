# Merge receipts live on the item, not in the events ledger

## What changed

One standalone or lane merge produces bookkeeping five different readers need
after the merge is over: crash recovery, the terminal QA identity gate, lane
retirement authorization, release carried-work attribution, and the session
card's merge stage strip. That bookkeeping used to be written as a
`StandaloneMergeReceiptRecorded` event and read back out of the events ledger.

It is now written to the merged item's own `item_sections` document —
`Merge Receipts` — keyed by the merge identity (branch and target), through
the registered `merge_receipt.record` / `merge_receipt.get` functions. The
event name is retired.

## Why

Events are disposable telemetry. Retention prunes them, an emission may be
filtered or fail, and nothing promises a row is still there later. Everything
the five readers wanted from the receipt is the opposite of disposable:

- A merge deletes the branch ref and removes the lane once the branch is
  contained by its target. From then on `merge-base` reports an empty diff and
  the lane directory is gone, so the receipt is the *only* record of what the
  branch changed and which commit landed. If it expires, a retry cannot
  converge and a landed-and-removed lane reads as "contents unaccounted for".
- The terminal QA gate expands the heads a blocking run may be recorded
  against from the same receipt. An expired receipt rejects valid proof.
- Release attribution maps range commits back to items from the same recorded
  lineage. An expired receipt silently drops an item from a release's carried
  work and falls back to commit-message heuristics.

The item is the durable owner those facts already belong to: the receipt
describes that item's merge, and it should last exactly as long as the item.
`item_sections` is that owner, already used for the item's execution evidence,
so this needed no new table and no new ledger.

## The failure record is current state, not chronology

The session card used to paint its merge stage red by scanning merge
failure and success events newest-first and taking whichever came first. Two
things go wrong there: expiry can erase an unresolved failure entirely, and
unequal retention can leave an old failure standing after the success that
resolved it has already been pruned.

The receipt entry carries the failure the last attempt on that identity ended
on, and a landed or settled merge drops it. There is one value to read and it
describes the merge's current state, so neither failure mode is reachable.

Both halves are written at one chokepoint —
`yoke_core.engines.merge_worktree_events._emit_merge_event` — which every
merge failure and settling success in both the standalone and lane paths
already passes through. The durable write happens there first; the event is
emitted beside it as telemetry and remains free to fail.

## What stayed the same

- The receipt shape (branch, target, implementation commit, merge commit,
  changed files, observed checks) is unchanged, and so is the fold that lets
  the pre-merge write and the completed write each contribute their half.
- Every refusal the readers already made stays: an incomplete receipt still
  refuses recovery, a recorded commit not contained by the target still
  refuses, a missing lane directory without a completed receipt still refuses
  retirement, and stale QA proof is still rejected. A missing directory is
  never inferred to be safe.
- The write is still advisory and never unwinds a merge. A control-plane
  hiccup degrades crash recovery; refusing the merge over it would trade a
  rare failure for a common one. The note reaches the caller's warnings so the
  degradation is visible rather than silent.
- No event was deleted and no retention policy changed. The historical rows
  remain; the registry entry is marked retired so they do not read as rogue.
