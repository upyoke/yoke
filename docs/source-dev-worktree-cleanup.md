# Source-Dev Worktree Cleanup

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately -- before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

Use this only for source-dev/admin cleanup of Yoke checkout worktrees. Product
project setup does not require this recipe.

The safety question is not "is the branch merged into my current checkout?"
The safety question is "is the branch tip an ancestor of the intended base I am
cleaning against, and is the worktree clean?"

## Audit

Run the audit from the main Yoke checkout. Set `base_ref` explicitly. For this
repository's stage lane, use `origin/stage`; for main cleanup, use
`origin/main`.

```bash
base_ref=origin/stage

for wt in /Users/dev/yoke/.worktrees/*; do
  branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD || true)
  head=$(git -C "$wt" rev-parse --short HEAD)
  wt_status=$(git -C "$wt" status --porcelain --ignored=matching --untracked-files=all)

  printf 'worktree=%s\nbranch=%s\nhead=%s\nclean=%s\n' \
    "$wt" "$branch" "$head" "$([ -z "$wt_status" ] && echo yes || echo no)"

  if [ -n "$branch" ]; then
    if git -C /Users/dev/yoke merge-base --is-ancestor "$branch" "$base_ref"; then
      echo "ancestor_of_${base_ref}=yes"
    else
      echo "ancestor_of_${base_ref}=no"
    fi
  fi
  printf '\n'
done
```

Do not name a shell variable `status` in zsh; it is a readonly special
parameter. Use `wt_status` or run the loop under `sh`.

## Remove One Merged Worktree

Only remove a worktree when all of these are true:

- the worktree status is clean
- the worktree has no ignored or untracked evidence files
- the branch tip is an ancestor of the intended base ref
- no active work claim still points at the worktree
- the branch has no work you still need as a standalone evidence checkpoint

Recheck those facts inline immediately before deleting:

```bash
repo=/Users/dev/yoke
base_ref=origin/stage
wt=/Users/dev/yoke/.worktrees/example-worktree
branch=codex/example-branch

test -z "$(git -C "$wt" status --porcelain --ignored=matching --untracked-files=all)"
python3 -m runtime.harness.harness_sessions who-claims 0
git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref"
git -C "$repo" worktree remove "$wt"
git -C "$repo" branch -D "$branch"
```

Replace `0` in the claim lookup with the item id for item worktrees, or inspect
the active work claim rows before deleting non-item source-dev worktrees.

`git branch -d` is not the right safety check when the intended base is not the
current `HEAD`; it checks merge status relative to the current checkout. Use
`merge-base --is-ancestor "$branch" "$base_ref"` as the guard, then delete the
local branch only after that guard passes.

Avoid `git worktree remove --force` for cleanup. If normal removal refuses,
inspect the worktree state and preserve or commit the work before retrying.

## Keep Non-Ancestor Evidence Branches

If `git cherry -v "$base_ref" "$branch"` prints `+` commits and those commits
touch only strategy/evidence docs, do not delete the branch as "merged" without
first deciding whether that evidence was intentionally superseded. Record the
decision in the relevant plan or archive before cleanup.
