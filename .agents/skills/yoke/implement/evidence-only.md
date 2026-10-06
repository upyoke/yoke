# /yoke implement — evidence-only items

Read this when the work makes no repository change, or when the done
transition or usher hit the empty-branch guard (exit 8) on such an item.

Items that require no code changes (validation, proof, guidance updates) pass `--no-worktree` to `/yoke implement` at implementation entry. This leaves the item without an active implementation lane in `item_worktrees`, so the done-transition engine (`yoke_core.engines.done_transition`) skips the empty-branch guard (exit 8).

**If an evidence-only item entered implementation WITHOUT `--no-worktree`** and later hits exit 8 during done-transition or usher, the recovery path is:
1. Complete the caller's rollback to `implemented`; lane release is refused at every other status.
2. Ensure this session holds the item claim: `yoke claims work acquire --item PREFIX-N --reason evidence-only-recovery`.
3. Read the registered implementation-lane path and prove it has no modified tracked or untracked files:

```bash
_wt_path=$(yoke item-worktrees get PREFIX-N \
 --lane-role implementation --field path)
if [ -z "$_wt_path" ] || [ "$_wt_path" = "null" ] || [ ! -d "$_wt_path" ]; then
 echo "Blocked: the registered worktree path cannot be verified."
 exit 1
fi
_wt_dirty=$(git -C "$_wt_path" status --porcelain \
 --untracked-files=all)
_wt_git_rc=$?
if [ "$_wt_git_rc" -ne 0 ] || [ -n "$_wt_dirty" ]; then
 echo "Blocked: preserve or commit every worktree file before lane release."
 exit 1
fi
```

4. Immediately release the attested lane: `yoke item-worktrees release PREFIX-N --all-active --reason evidence-only-recovery`. The adapter repeats the branch and cleanliness checks, and the server requires a post-implementation stage of the pinned workflow with exactly one active implementation lane matching the attestation.
5. Re-run the done-transition or usher command.

The empty-branch guard exists to catch accidental merges of branches with no work. For items that intentionally have no code changes, the guard is a false positive — releasing the active lane records is the canonical recovery.
