# /yoke advance step 3 — worktree re-entry

## 3. Worktree Re-entry

When the advance target triggers re-entry into the current worktree:
- current = `implementing`, advance target = `implementation` (or `implementing`)
- current = `reviewing-implementation`, advance target = `reviewing-implementation`
- current = `reviewing-implementation`, advance target = `implementation` (re-entry)

Locates the existing worktree, prepares `WORKTREE_PATH`, and resumes the implementation/review loop. Do **not** stop after surfacing the path.

```bash
_item_project=$(yoke items get {N} project 2>/dev/null)
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "" ]; then
 _wt_repo=$(yoke projects get --project "$_item_project" --field repo_path)
else
 _wt_repo=$(git rev-parse --show-toplevel)
fi

if [ "$_worktree_policy" = "none" ]; then
 # Laneless workflow: there is no worktree to re-enter. The work happens
 # in place under the session's existing write authority.
 _wt_branch=""
 WORKTREE_PATH=""
elif [ "$_worktree_policy" = "single_implementation_lane" ]; then
 _wt_branch=$(yoke item-worktrees get PREFIX-N \
  --lane-role implementation --field branch 2>/dev/null)
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
- If `_wt_branch` set → check `$_wt_repo/.worktrees/$_wt_branch`.
 - Directory exists → set `WORKTREE_PATH` to the absolute path and continue.
 - Missing → recreate through the source-dev/admin worktree helper, update DB, set `WORKTREE_PATH`, and continue. No registered product CLI wrapper exists for direct worktree creation; normal operators use `/yoke advance PREFIX-N implementation`.
- If `_wt_branch` empty under a lane-bearing policy → create new worktree, update DB, set `WORKTREE_PATH`, and continue.

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
