# Usher — sequential lane landing

For each ordered registered lane, verify actual checkout branch. A stored/
actual mismatch warns with both identities and selects the verified actual
branch. Read exact registered path; no branch-to-directory synthesis.
Commit only known uncommitted Tester review artifacts in this authorized lane,
with exact paths and descriptive message; preserve unrelated state/errors.
Resolve target from project's default branch and carry parent's complete ref.

```text
git -C ABSOLUTE_REGISTERED_LANE branch --show-current
git -C ABSOLUTE_REGISTERED_LANE status --short
yoke watch merge merge-worktree -- BRANCH DEFAULT_BRANCH PREFIX-N
```

Pass force-lock/skip-simulation only when explicitly authorized; no local
fallback for queue policy. Engine owns rebase/generated resolution/tests/
App-bound PR+CI+merge, branch/checkout cleanup and terminal task/GitHub receipts.
Read actual outcome, merged PR/commit and target sync. Never supplement it
with bypass env vars or internal update_status terminal writes.

After each successful landing, verify target synchronization before trusting
main's files. Engine owns sync; failure reports merge_target_sync_failed and
exact recovery, preserves dirty state and skips unverifiable checks. Don't
claim a postmerge pass or advance bookkeeping against stale checkout.
Reverify the same statically checkable parent criteria against the verified
merged target (not a removed lane), with pre/post progress and PASS/FAIL.
Runtime-only checks explicitly report SKIP (runtime-only) and retain original
execution proof; static checks are not a new runtime suite.

A criterion that passed premerge and now fails is POST-MERGE AC REGRESSION:
halt immediately, name criterion/reason/PR/branch and inspect whether generated
resolution lost intended content. Operator investigation/current-item fix is
required before later lanes. Report pass_count/verifiable_count and runtime
skip count. Missing criteria skips postcheck silently after preflight's warning.

Failure after rebase belongs here: halt, report failing tests/reason, resolve
under this item/claim, commit and resume same procedure. Future/planned owners
do not waive it; a live conflict/decision is reported before proceeding.
Conflict3 uses [recovery](merge-conflicts.md). Already-landed lanes reuse receipts
on retry. Continue to [bookkeeping](merge-bookkeeping.md) only after every lane.
