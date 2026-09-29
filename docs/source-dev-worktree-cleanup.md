# Source-Dev Worktree Cleanup

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately -- before retrying, before moving on.
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
python3 -m yoke_core.hooks.sessions_cli who-claims 0
git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref"
git -C "$repo" worktree remove "$wt"
git -C "$repo" branch -d "$branch"
```

Replace `0` in the claim lookup with the item id for item worktrees, or inspect
the active work claim rows before deleting non-item source-dev worktrees.

`git branch -d` is not the right safety check when the intended base is not the
current `HEAD`; it checks merge status relative to the current checkout. Use
`merge-base --is-ancestor "$branch" "$base_ref"` as the guard, then use normal
`branch -d` only after that guard passes. If normal deletion refuses because
the main checkout is not on the intended base, preserve the ref or switch the
main checkout to that base and repeat the complete audit. Do not substitute
`branch -D`.

Avoid `git worktree remove --force` for cleanup. If normal removal refuses,
inspect the worktree state and preserve or commit the work before retrying.

## Automatic Cleanup Contract

Merge preflight automatically prunes only worktrees registered beneath the
repository's managed `.worktrees/` or `.claude/worktrees/` roots. A candidate
must have one exact terminal DB owner, no active work claim or harness session,
a clean status including ignored and untracked files, and a branch tip that is
an ancestor of the freshly fetched target. For each lane it first proves and
deletes the exact remote ref (or proves it already absent) via the shared
`delete_remote_branch_if_merged` helper; only then does removal use normal
`git worktree remove`, followed by normal `git branch -d`. Incomplete remote
cleanup preserves the local worktree and branch for a later safe retry.

Done-transition uses the same fail-closed, remote-first evidence for its
current item lane and the same shared helper — never a duplicate remote-delete
path. Local `git branch -d` proves ancestry against the refreshed
`origin/<base>` ref, not upstream tracking. If remote-ref, worktree, or
local-ref cleanup is refused, the item's worktree metadata remains intact so
ownership is not lost and a later safe sweep can retry; the done runner does
not complete happy-path close-out while that cleanup is incomplete.

Unregistered directories, ambiguous owners, dirty or ignored content,
unavailable claim/DB state, non-ancestor branches, and removal refusals are
preserved and reported. Automatic cleanup never uses filesystem `rm -rf`,
forced worktree removal, or forced branch deletion. `--keep-remote` remains
the only intentional skip of remote delete (ephemeral environments).

### Lane residue and project-declared renders

A lane directory is disposable only when everything git reports in it is a
cache the shared residue policy can name — build output, virtualenvs, tool
caches, the operating-layer state Yoke renders into every checkout — or a path
the owning project declared through its `project-policy` capability's
`disposable_generated_paths`. Ignored is not disposable on its own: a local
database, a credential file, and scratch notes are all ignored and none of them
is the repository's to delete, so an undeclared ignored path preserves the lane
and is reported as unknown residue.

That is why a product surface which renders a gitignored view into every
checkout must be declared. In this repository the Atlas renderer writes
`docs/atlas.md` into every lane, so the `yoke` project declares it; without
that declaration every landed lane refused retirement on it, and both the
worktree and the merged remote branch survived. Read the live declaration with
`yoke projects capability-settings get --project <slug> --cap-type
project-policy`.

### Deploy-run driver worktrees

A self-deploy run pins its driver source in a detached worktree at
`.worktrees/deploy-<run-id>` so the driver reads a tree a merge landing cannot
move underneath it. Because it carries no branch, it is absent from the
branch-bearing registry the lane paths read, and no item owns it — so the lane
sweep and `HC-worktree-health` could not see one at all while it consumed the
same `max_active_worktrees` slot an item lane does.

It is retired from its run's own status instead, by whichever of these comes
first: a self-deploy sweeping before it pins its own source, the machine-wide
sweep any landing runs, or the health check's own repair:

```text
yoke watch doctor -- --only HC-worktree-health --fix
```

Only a status the run-status vocabulary names terminal (`succeeded`, `failed`,
`cancelled`) releases the directory. A run still `created` or `executing` is not a finding. An empty,
unrecognised, or unreadable status, a tree holding anything the residue policy
will not name, and a tree the sweeping process is itself executing from all
keep the directory with the reason named — reclaiming a live run's pinned
source would pull the ground out from under a driver mid-deploy.

Removal is the same two steps the item lanes use: clear named and declared
caches (a driver that executed there left `__pycache__` behind), then a
non-force `git worktree remove`. Force is never used.

When the cap refuses a new lane it separates the two kinds and gives each its
own recovery, because merging is not the recovery for a deploy-run lane:

```text
max_active_worktrees limit reached (50 active + 1 pending > 50). Merge
existing worktrees before creating more. Item lanes: .... 36 slot(s) are held
by deploy-run driver trees, which no merge retires — run `yoke watch doctor --
--only HC-worktree-health --fix` to retire the finished ones. Deploy-run
lanes: ...
```

## Keep Non-Ancestor Evidence Branches

If `git cherry -v "$base_ref" "$branch"` prints `+` commits and those commits
touch only strategy/evidence docs, do not delete the branch as "merged" without
first deciding whether that evidence was intentionally superseded. Record the
decision in the relevant plan or archive before cleanup.
