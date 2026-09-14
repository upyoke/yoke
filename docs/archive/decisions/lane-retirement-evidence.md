# What proves a lane may be retired

A lane is a worktree directory, a local branch, a remote branch, and the
control-plane row that records where they live. When its item goes terminal
the control plane releases the row inside the status transaction, and the
machine-local half — the directory and the two branches — has to be retired
separately, because only the machine holding the checkout can do it.

Two boundaries reach that work: the landing that merges a standalone item,
and the machine-wide merged-lane sweep that every landing runs afterwards so
a lane an earlier landing preserved is examined again. They used to answer
the same two questions differently, and a lane survived whichever answer was
stricter while its item read as finished.

## Landed means the target retains the change, not the commit

Both boundaries proved landing with `merge-base --is-ancestor`. That is only
true of a lane whose own commits reached the target — a rebase-and-merge or
a squash rewrites them, so ancestry reads the lane as unmerged forever even
though `origin/main` holds every change it carried. `git branch -d` makes
exactly the same reading, so the branch could not be deleted either.

`branch_landed_evidence` reads twice: ancestry first, then patch equivalence
(`git cherry`) when ancestry fails. Every commit pairing with an equivalent
already in the target means the branch holds nothing unique. It fails toward
preserving — unreadable history, a merge commit `git cherry` skips, or one
commit with no equivalent keeps the lane and names why.

Because that proof is stronger than git's own, the forced delete lives with
it: `delete_landed_branch` runs `branch -D` only behind matching evidence,
and the static guard in `test_merge_cleanup_destructive_guard` keeps every
other lane module from issuing one. Deleting a branch on *item status* or a
matching title was never an option — status says the work is finished, not
that this repository already holds it.

## Ignored is not disposable

The landing boundary treated any git-ignored residue as disposable and
removed the worktree with `--force`; the sweep removed a named allowlist of
caches and refused everything else. So one lane could be deleted by the
boundary that landed it and kept by the sweep that revisited it, and a local
database, a credential file, or an operator's scratch notes — all ordinary
ignored content — sat inside the deletable set.

`merge_worktree_cleanliness` is now the one residue policy both read:
tracked and untracked content is work, an ignored path matching the
named-cache allowlist is disposable, and any other ignored path is unknown
and therefore kept with its name in the reason. A repository ignore rule
says "do not track this", never "this may be deleted". The cost of the
conservative reading is that a lane holding repo-declared build output under
an unrecognized name waits for an operator; the cost of the other reading is
measured in lost work.

## Retirement runs wherever an item becomes, or already is, terminal

Terminal status commits before retirement runs, and retirement can refuse
for reasons that later stop being true. Nothing retries it on a schedule, so
every path that reaches a terminal item takes it: the close-out that lands
the merge, both re-entries that find the landing already recorded, and the
cancel that makes an item terminal without any merge at all. Every step of
it is proof-gated, so the repeat is safe, and a lane whose branch and
directory are both already gone is skipped rather than reported.
