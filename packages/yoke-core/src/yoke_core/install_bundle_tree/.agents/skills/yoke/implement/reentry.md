# /yoke implement phase 2 — re-enter the lane

Read this when the live stage is inside the `implement` segment but past its
entry stage — for an issue, `implementing` or `reviewing-implementation`. It
recovers the lane, sets `WORKTREE_PATH`, and resumes the loop. Do **not** stop
after surfacing the path.

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
else
 echo "CONTRACT ERROR: implement owns only single-lane or laneless policies; PREFIX-N pins $_worktree_policy."
 echo "Run the skill its pinned binding names for that stage."
 exit 1
fi
```

- Policy `none` → leave `WORKTREE_PATH` empty and continue; never create a lane
  for a laneless workflow.
- `_wt_path` set and the directory exists → set `WORKTREE_PATH` to it and
  continue.
- `_wt_path` set but the directory is missing, or `_wt_branch` empty under a
  lane-bearing policy → re-run the engine entry,
  `yoke advance implementation-entry --item PREFIX-N`, which reuses or
  recreates the registered lane without repeating the status write. A lane row
  with no `path` is a broken record, not a path to compose: repair it with
  `yoke item-worktrees path-record`.

After `WORKTREE_PATH` is ready, resume where the live stage says:

- The implementation stage (`implementing` for an issue) → continue
  [`implementing/SKILL.md`](implementing/SKILL.md) in the recovered lane.
- The review stage (`reviewing-implementation` for an issue) → continue the
  review loop in [`review.md`](review.md) in the same lane.

Never stop with "Want me to review now?" or a numbered handoff menu unless a
real blocker prevents continued work.
