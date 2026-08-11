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

The terminal done-gate binds QA evidence to the item's merging commit, and
the same evidence record names the files the landing changed. A queue merge
produces neither of those locally: GitHub creates the merge commit, so no
lane-local commit carries it, and the head the queue merged need not be the
one the checkout holds, so a local diff is not authoritative for what
landed. The member's close-out therefore reads both from the pull request —
the merge SHA and the file listing — and records them where the gate looks.
The done-transition engine must likewise surface, not swallow, a refused
status write, so a landed item never strands without saying why.

Lane retirement has the same shape. The local engine removes the worktree it
merged from as its own last step; a queue landing has no such step, so its
close-out retires the lane explicitly — remote branch first, then the worktree,
the control-plane row, and the local branch — proving containment against a
freshly fetched `origin/<target>` rather than against the local target, which
still lags a merge this checkout never made. Without it every landed member
leaves a directory and two branches behind.

Convergence is bounded by what merged. Re-entry finds a branch's pull request
in any state, so a lane that committed again after its pull request merged
still matches it by name; the landing therefore converges only on a merged
pull request whose head is the lane head, and opens a fresh one otherwise.
Converging anyway writes a receipt binding the new head to the old merge
commit — evidence for work that never reached `main`.

## Rollback

Disable or delete the `merge-queue-main` ruleset and remove the project's
`merge_queue` capability declaration; route selection then returns to the
standalone merge engine. Do neither halfway: a declared capability with no
active `merge_queue` branch rule refuses to merge rather than falling back.
