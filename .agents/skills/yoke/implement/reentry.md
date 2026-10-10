# /yoke implement — re-enter the lane

After the claim-first step in [entry.md](entry.md), recover the registered
lane. Never compose its path from the current project root.

```bash
if [ "$_worktree_policy" = "none" ]; then
 WORKTREE_PATH=""
 _wt_branch=""
elif [ "$_worktree_policy" = "single_implementation_lane" ]; then
 _wt_branch=$(yoke item-worktrees get PREFIX-N --lane-role implementation --field branch)
 _wt_path=$(yoke item-worktrees get PREFIX-N --lane-role implementation --field path)
else
 echo "CONTRACT ERROR: live binding does not belong to single-lane Implement."
 exit 1
fi
```

On that contract error, stop this segment. Run the skill its pinned binding
names for the live stage; never choose a remembered workflow command.

| Registered state | Action |
|---|---|
| none policy | No lane; continue under existing write authority |
| Path exists | Set WORKTREE_PATH to that exact path |
| Path directory missing or branch empty | Re-run implementation-entry engine; reuse/recreate without repeating status |
| Lane row missing path | Repair through `yoke item-worktrees path-record`; do not guess a path |

The pinned implementation stage resumes [implementing](implementing/SKILL.md);
its review stage resumes [review](review.md). Continue in this session without
a menu or turn-ending checkpoint unless a real blocker prevents work.
