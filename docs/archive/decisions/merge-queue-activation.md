# Merge queue on main: one integration gate per train

## Decision

Yoke item branches land on `main` through the GitHub merge queue. The
desired ruleset and repository settings live in
[`.yoke/merge-queue.json`](../../../.yoke/merge-queue.json) — that file is
the operator-edited source of truth. Apply it with
`yoke github merge-queue apply --project yoke` (Administration: write on
the App). Doctor `HC-merge-queue-binding` diffs the live ruleset parameters
and `allow_auto_merge` against the declaration so grouping flips, dropped
required checks, widened bypass, or a disabled auto-merge turn red. The
check reads the declaration from the project checkout when the host has
one — so an operator sees uncommitted retunes — and otherwise fetches it
from the repository at the default branch head, which is what lets a
hosted runner holding no checkout run the same parameter diff.

The declared ruleset carries a `merge_queue` rule (merge method MERGE,
HEADGREEN grouping, trains of five entries with a one-minute wait to gather
them, capped at 5, 60-minute check timeout) and `required_status_checks`
naming every yoke-ci check that gates both queue entry and the train
(`repo-contracts`, `container`, `browser_runtime / browser-runtime`, and one
`test-shard` context per shard per Python version). Repository admins carry an always-bypass so operator pushes
to `main` and break-glass fixes keep working; the bypass is an operator escape
hatch, not an agent merge path. Classic branch protection still requires
`signature-check` (CLA); that surface stays under
`HC-branch-protection-required-check`, not the merge-queue declaration.

## Why

Measured on a single working day of eleven parallel lanes: the serialized
exact-final-tree merge discipline ran the full CI suite 21 times, roughly 9
of them wasted re-proving trees that a neighbor's merge had already
invalidated. A queue amortizes that: every branch proves itself once on its
own tree, and one `merge_group` run proves the combined result for the whole
train, with GitHub ejecting only the culprit on a red train.

Hand-applied GitHub switches drifted within an hour of the first activation
record (ALLGREEN → HEADGREEN). Encoding the shape in-repo closes that gap:
retune by editing the declaration and re-applying; drift without a re-apply
fails the doctor.

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

## Why trains batch, and what pays for it

The queue already builds speculatively: up to `max_entries_to_build` nested
groups at once — `[A]`, `[A,B]`, `[A,B,C]` — each proving a deeper prefix of
the queue against the same base. Batching does not reduce how many builds
run. What it decides is whether those builds are kept.

With a minimum of one, the shallowest green group merged alone the moment it
went green. The base advanced, every deeper speculative group was suddenly
built against a base that no longer existed, and all of that finished work
was discarded and rebuilt. The cost was a rebuild cascade, not serialization.
Reading the queue branch names as trains of one is the easy mistake and a
wrong one: the branch is named for its group's head pull request and says
nothing about the group's depth. Count the group, not the name.

Waiting for a group of five lets the queue merge the deepest green group it
has, consuming those speculative builds instead of throwing them away.

The wait is the subtle half. `min_entries_to_merge` counts entries **already
queued**, not arrivals still to come, so a long wait does not accumulate a
batch — it only delays releasing an entry that is genuinely alone. The timer
exists only for the quiet case, and a minute caps it.

**The full isolated entry run is what makes batching safe, and narrowing it is
the tempting mistake.** Every member of a group has already been proven green
*alone*, so a group failure is by construction an interaction failure rather
than an unattributed one, and GitHub's automatic bisect rarely has to run.
Trimming the entry run to a change-impacted selection would look like a
saving and would remove both the isolation proof and cheap attribution — a red
train would no longer tell you whether a member is broken or merely
incompatible with its neighbours. The entry run stays whole.

Shard width is the larger lever, and orthogonal to all of this: it is
parallelism inside one run, so it shortens every one of those concurrent
speculative builds rather than a single train, and it touches neither
isolation nor attribution. Its ceiling is the fixed setup cost each shard
pays, not runner capacity — see `yoke_core.tools.ci_shards`, which owns the
count.

## Rollback

Disable or delete the `merge-queue-main` ruleset and remove the project's
`merge_queue` capability declaration; route selection then returns to the
standalone merge engine. Do neither halfway: a declared capability with no
active `merge_queue` branch rule refuses to merge rather than falling back.
Clear the declaration file only after the live ruleset is gone, or doctor
will report parameter drift against a missing live rule.
