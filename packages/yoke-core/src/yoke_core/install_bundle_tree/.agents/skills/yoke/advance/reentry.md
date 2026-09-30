# /yoke advance step 3 — worktree re-entry

## 3. Worktree Re-entry

When the advance target triggers re-entry into the current worktree:
- current = `implementing`, advance target = `implementation` (or `implementing`)
- current = `reviewing-implementation`, advance target = `reviewing-implementation`
- current = `reviewing-implementation`, advance target = `implementation` (re-entry)

Locates the existing worktree, prepares `WORKTREE_PATH`, and resumes the implementation/review loop. Do **not** stop after surfacing the path.

```bash
if [ "$_worktree_policy" = "none" ]; then
 # Laneless workflow: there is no worktree to re-enter. The work happens
 # in place under the session's existing write authority.
 _wt_branch=""
 WORKTREE_PATH=""
elif [ "$_worktree_policy" = "single_implementation_lane" ]; then
 # The registered lane row carries its own absolute path. Read it rather
 # than composing one from a project root: the lane may live in another
 # project's checkout, and a composed path is a guess either way.
 _wt_branch=$(yoke item-worktrees get PREFIX-N \
  --lane-role implementation --field branch 2>/dev/null)
 _wt_path=$(yoke item-worktrees get PREFIX-N \
  --lane-role implementation --field path 2>/dev/null)
elif [ "$_worktree_policy" = "worker_and_integration_lanes" ] \
 || [ "$_worktree_policy" = "worker_lanes_optional_integration" ]; then
 if [ "$_current_skill" = "conduct" ]; then
  echo "CONTRACT ERROR: the pinned conduct skill owns PREFIX-N's task lanes."
  echo "Use /yoke conduct PREFIX-N to re-enter or advance a generated task lane."
 else
  echo "CONTRACT ERROR: skill $_current_skill owns a multi-lane policy that advance cannot select."
 fi
 exit 1
else
 echo "CONTRACT ERROR: unsupported pinned worktree policy $_worktree_policy."
 exit 1
fi
```

- If the policy is `none` → leave `WORKTREE_PATH` empty and continue; never create a lane for a laneless workflow.
- If `_wt_path` set → check that directory.
 - Directory exists → set `WORKTREE_PATH` to it and continue.
 - Missing → recreate through the source-dev/admin worktree helper, update DB, set `WORKTREE_PATH`, and continue. No registered product CLI wrapper exists for direct worktree creation; normal operators use `/yoke advance PREFIX-N implementation`.
- If `_wt_branch` empty under a lane-bearing policy → create new worktree, update DB, set `WORKTREE_PATH`, and continue. A lane row with no `path` is a broken record, not a path to compose: repair it with `yoke item-worktrees path-record`.

After `WORKTREE_PATH` is ready:
- If current status is `implementing`, continue with step 4 as the normal single-lane implementation loop selected by the pinned `advance` binding.
- If current status is `reviewing-implementation`, resume the review loop in the same worktree immediately:
 1. Review the current branch against the spec and acceptance criteria.
 2. Make any follow-up fixes in that same worktree.
 3. Re-run the relevant verification and refresh QA evidence.
 4. When review actually passes, immediately run `/yoke advance PREFIX-N reviewed-implementation`.
 **Commit invariant:** The advance to `reviewed-implementation` must not leave the worktree dirty. Finalize step 9 handles this automatically — when `WORKTREE_PATH` is set, it stages worktree changes (`git -C "$WORKTREE_PATH" add -A`) before checking the index. Review-loop fixes, including newly created files, are committed as part of the advance, not left behind.
- Never stop with "Want me to review now?" or a numbered handoff menu unless a real blocker prevents continued work.

Next: [`phase-dispatch.md`](phase-dispatch.md).
