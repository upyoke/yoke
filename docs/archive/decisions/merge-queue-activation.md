# Merge queue on main: one integration gate per train

## Decision

Yoke item branches land on `main` through the GitHub merge queue. A branch
ruleset on `main` carries two rules: `merge_queue` (merge method MERGE,
ALLGREEN grouping, 5-minute batching window, trains capped at 5 entries) and
`required_status_checks` naming every yoke-ci check (`repo-contracts`,
`container`, and the eight `test-shard` matrix checks). The same required
checks gate both queue entry (each PR's own CI is its entry ticket) and the
train (`merge_group` runs one combined-head CI per batch).

Repository admins carry an always-bypass so operator pushes to `main`
(done-transition bookkeeping commits, break-glass fixes) and the pre-queue
merge engine keep working; the bypass is an operator escape hatch, not an
agent merge path.

## Why

Measured on a single working day of eleven parallel lanes: the serialized
exact-final-tree merge discipline ran the full CI suite 21 times, roughly 9
of them wasted re-proving trees that a neighbor's merge had already
invalidated. A queue amortizes that: every branch proves itself once on its
own tree, and one `merge_group` run proves the combined result for the whole
train, with GitHub ejecting only the culprit on a red train.

## Coupled fixes

The terminal done-gate binds QA evidence to the item's merging commit. A
queue merge commit is created by GitHub and never exists as a lane-local
commit, so the merge boundary must record the merged SHA where the gate can
read it (Execution Evidence), and the done-transition engine must surface —
not swallow — a refused status write. Both fixes ride the close-out
stranding item; until they land, a queue-merged item is settled by recording
the merged SHA in its Execution Evidence section and re-running
done-transition.

## Rollback

Disable or delete the `merge-queue-main` ruleset and remove the project's
`merge_queue` capability declaration; route selection then returns to the
standalone merge engine. Do neither halfway: a declared capability with no
active `merge_queue` branch rule refuses to merge rather than falling back.
