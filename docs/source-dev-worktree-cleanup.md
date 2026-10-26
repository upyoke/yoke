# Source-Dev Worktree Cleanup

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
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
yoke claims work holder-get --path "$wt" --json
git -C "$repo" merge-base --is-ancestor "$branch" "$base_ref"
git -C "$repo" worktree remove "$wt"
git -C "$repo" branch -d "$branch"
```

Inspect the registered holder read before running the removal commands. A named
active holder, an unavailable claim read, or unresolved ownership preserves the
worktree; a successful read alone is not permission to remove it.

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

The standing prod relay (`yoke relay status`) sweeps every checkout its
connection maps once when it starts and then every 15 minutes, on a thread
its poll loop never waits for. That periodic sweep is what retires a lane
whose item closed anywhere else — a release settled on a hosted control
plane, a queue landing, a lane an earlier pass kept. The relay log names
each lane removed and each lane kept with its reason, under `lane sweep:`.
A stage relay never sweeps: it would judge real lanes against a disposable
rehearsal database, so it logs that it is off. Merge preflight, a standalone
close-out and lane creation at the worktree cap run the same sweep, and only
one sweep runs in a checkout at a time; one that finds another running skips
with `another lane sweep is running in this checkout`.

The sweep prunes only worktrees registered beneath the repository's managed
`.worktrees/` or `.claude/worktrees/` roots, each through the same per-lane
proof a landing applies. A candidate must have one exact terminal DB owner
(a lane several tasks of one epic shared is owned by that epic once every
task finished and the epic is done or cancelled), no active work claim or
harness session, a clean status including ignored and untracked files, and a
branch the freshly fetched target retains: by ancestry, by patch
equivalence, or because its commits net to no change at all. For each lane it first proves and
deletes the exact remote ref (or proves it already absent) via the shared
`delete_remote_branch_if_merged` helper; only then is the proved-clean worktree
removed, followed by normal `git branch -d`. Incomplete remote cleanup
preserves the local worktree and branch for a later safe retry.

Each successfully removed lane also retires its `item_worktrees` row through
`item_worktrees.release_merged_lane`, including a registered lane whose folder
is already absent. A lane folder, named cache, or removal tombstone that
disappears after the sweep has read it counts as removed, and the sweep
continues with the lanes behind it. A finished worker can retire while its parent item stays
open; released rows cannot compete with the surviving lane as a merge source.
The authority verdict supplies the owner's public `item_ref`. If an older
server omits it, `prune_owner_identity_unavailable` preserves the lane: update
the serving control plane, then retry the sweep. A failed row release prints
the stranded branch and cause; restore control-plane access and ask the
control-plane operator to retry `item_worktrees.release_merged_lane` for that
item and branch. Preserved folders retain their active rows.

Removal is resumable, because `git worktree remove` deletes files one by one
and drops git's record last: killed midway, it stranded a registered,
half-deleted tree. Every removal path instead renames the worktree to a
`.removing-<name>-<id>` tombstone in its managed root (one atomic step), runs
`git worktree prune`, then deletes the tombstone. Any later sweep or
`HC-worktree-health --fix` finishes a tombstone an interruption left behind.
A removal runs to completion once started rather than under a caller's
shrinking deadline; a doctor check starts one only with at least 10 seconds of
its budget left and otherwise defers it with the reason named. A tree whose
only changes are deleted tracked files is an interrupted removal: once its
branch is proved landed, cleanup completes it rather than preserving it as
dirty work.

Done-transition uses the same fail-closed, remote-first evidence for its
current item lane and the same shared helper — never a duplicate remote-delete
path. Local `git branch -d` proves ancestry against the refreshed
`origin/<base>` ref, not upstream tracking. If remote-ref, worktree, or
local-ref cleanup is refused, the item's worktree metadata remains intact so
ownership is not lost and a later safe sweep can retry; the done runner does
not complete happy-path close-out while that cleanup is incomplete.

A deployment run retires no lanes. It settles where its control plane runs,
often a hosted server with no checkout, and the status write has already
released each member's lane rows and claims; the relay on the machine that
holds a member's lanes removes them on its next sweep. Every lane the sweep
keeps is named in that relay's log with its reason.

`max_active_worktrees` counts the lanes doing work: unmerged item lanes and
deploy-run driver trees. An item lane that committed work its base branch
already carries is only its worker's directory until the relay's lane sweep
retires it after its item closes, so it holds no slot. A lane that has not committed yet is starting work and
counts; its branch reflog shows it never moved past the commit it was created
at.

A full checkout does not wait for the relay's next pass: when a new lane
would exceed the cap, creation first runs the same sweep against the lane's
base branch, then counts again and refuses only for what remains.

Unregistered directories, ambiguous owners, dirty or ignored content,
unavailable claim/DB state, non-ancestor branches, and removal refusals are
preserved and reported. Automatic cleanup of a done item's lanes never uses
forced worktree removal or forced branch deletion, and deletes files only
inside a tombstone git no longer registers, after the residue proof.
`--keep-remote` remains the only intentional skip of remote delete (ephemeral
environments).

### Cancelled items

Cancelling an item deletes all of its lanes, because cancelling says the work
is not wanted. `yoke items cancel` (or a lifecycle transition to `cancelled`)
force-removes every lane worktree of the item on the machine that ran it —
dirty, locked or unmerged — then deletes the local branch and the branch on
`origin`. Before deleting, it reads each lane's local head, remote head and
uncommitted path count, and writes them to the item's Progress Log under
`Cancelled lanes deleted` through `item_worktrees.cancelled_lanes.record`.
Use those SHAs to find discarded commits while git still holds the objects.
A closed pull request's GitHub ref stays on GitHub.

Every other machine deletes its copy on its relay's next lane sweep:
`merge.prune.authority_verdict` names the cancelled owner as
`cancelled_item_ref`, and the sweep deletes that lane the same way and
records it the same way. A live session whose workspace is the lane still
keeps it until that session ends. A step git refuses is printed as a warning
naming the lane, and the Progress Log record lists it under `not deleted`.

### Health-check report

`yoke watch doctor -- --only HC-worktree-health` reports terminal item lanes
still on disk, under the same proof, and removes none of them; the relay's
periodic lane sweep does that. A lane proved finished is reported as
`verified-safe; the relay's periodic lane sweep removes it`, and every other
lane names why it stays: dirty, locked, claimed, unmerged, or preserved. The
check reads every lane's cleanup-authority verdict in one
`merge.prune.authority_verdicts` call and proves branch ancestry with one
`git for-each-ref --merged` of each target as this checkout last fetched it.
A detached commit still gets its own ancestry read, and a branch the target
does not contain still gets the patch-equivalence proof. Residue status
names an ignored or untracked directory once, not every file inside it, so
the verdicts for a full set of lanes finish inside the shared check budget.
A lane that fails validation is reported with the reason; every other lane
in that batch is still judged. A detached checkout is `detached@<commit>`,
never an empty branch. If the authority read itself fails, the check names
the failure and preserves every lane. `--fix` still finishes interrupted
removals and retires finished deploy-run driver trees.

### Lane residue and project-declared renders

A lane directory is disposable only when everything git reports in it is a
cache the shared residue policy can name — build output, virtualenvs, tool
caches such as `.hypothesis`, the operating-layer state Yoke renders into every
checkout — or a path
the owning project declared through its `project-policy` capability's
`disposable_generated_paths`. Ignored is not disposable on its own: a local
database, a credential file, and scratch notes are all ignored and none of them
is the repository's to delete, so an undeclared ignored path preserves the lane
and is reported as unknown residue.

That is why a product surface which renders a gitignored view into every
checkout must be declared. In this repository the Atlas renderer writes
`docs/atlas.md` and the teaching build writes `docs/teaching/views/`. These
generated paths need disposable declarations. The retired `docs/teaching/live/`
path may remain declared to clean older lanes; the current builder removes it.
Without declarations, generated residue prevents lane and branch retirement. Add a missing render
with `yoke projects capability-settings merge --project <slug> --cap-type
project-policy --set 'disposable_generated_paths=[...]'`, repeating the
entries already declared. Read the live declaration with
`yoke projects capability-settings get --project <slug> --cap-type
project-policy`.

### Deploy-run driver worktrees

A Yoke self-release run, stage or production, pins its driver source in a
detached worktree at `.worktrees/deploy-<run-id>` so the driver reads a tree a
merge landing cannot move underneath it. Because it carries no branch, it is absent from the
branch-bearing registry the lane paths read, and no item owns it — so the lane
sweep and `HC-worktree-health` could not see one at all while it consumed the
same `max_active_worktrees` slot an item lane does.

It is retired from its run's own status instead, by whichever of these comes
first: a self-deploy sweeping before it pins its own source, the relay's
periodic lane sweep or the same sweep a landing or a full checkout's lane
creation runs, or the health check's own repair:

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
caches (a driver that executed there left `__pycache__` behind) and prove
nothing else remains, then the resumable tombstone removal. Force is never
used.

When the cap still refuses after that sweep, it sorts the counted slots by
what frees them and names how many landed lanes it left out:

- unmerged item lanes: merge them;
- driver trees whose run is not open: retire the finished ones with the doctor
  repair;
- driver trees of an open run: in use by that run's driver, and freed when the
  run finishes. They are never offered for retirement.

```text
max_active_worktrees limit reached (80 active + 1 pending > 80; 52 landed
lane(s) not counted). Merge existing worktrees before creating more. Item
lanes: .... 3 slot(s) are held by
deploy-run driver trees, which no merge retires — run `yoke watch doctor --
--only HC-worktree-health --fix` to retire the finished ones. Deploy-run
lanes: .... 1 slot(s) are in use by open deploy runs' drivers and free when
those runs finish. In-use deploy-run lanes: ...
```

`HC-worktree-health` lists the landed lanes of open items on their own line,
apart from its findings, so its report shows which lanes the cap leaves out:

```text
- 52 landed lane(s) await release close-out and are not counted against
max_active_worktrees: ...
```

## Keep Non-Ancestor Evidence Branches

If `git cherry -v "$base_ref" "$branch"` prints `+` commits and those commits
touch only strategy/evidence docs, do not delete the branch as "merged" without
first deciding whether that evidence was intentionally superseded. Record the
decision in the relevant plan or archive before cleanup.
