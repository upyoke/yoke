# Finishing the close-out a landed merge started

## The gap

A merge that lands is irreversible. Everything after it — the evidence record,
the GitHub sync, the terminal transition — is bookkeeping the item still owes,
and every failure in that stretch leaves the same wreckage: `merged_at` set, a
branch on the base branch, and an item that never reached `done`, needing an
operator to finish it by hand. Three distinct mechanisms produced that state.

**The process deleted the code it was still importing from.** The merge
engine's cleanup removes the lane worktree. When the running process had
resolved its own packages out of that lane, the lazy imports the close-out
still owed — GitHub sync reaching for the board rebuild, in one observed case —
searched a directory that no longer existed and raised `ImportError`. The merge
had already landed; the command exited non-zero on its way out.

**The terminal gate demanded one SHA that could not exist.** The gate refuses
an item whose blocking QA runs do not cover the tree that landed, and resolved
"the tree that landed" from Dash execution evidence, else the lane's recorded
commit. That column is written only by the post-commit head recorder, so it
only ever holds a lane-LOCAL commit. A merge commit created remotely — a PR
merge, and structurally every merge-queue `merge_group` commit — can never
appear in it, so the gate compared the runs' real merged SHA against
`<missing>` and refused. The single-SHA comparison was itself the deeper
problem: one merge legitimately proves two trees, the lane head the item's own
cases ran against and the integrated head the merge gate validated, and under a
merge queue the train's combined head is a commit no single member ever ran
against. No one value could satisfy every requirement, so every queue-landed
item would strand at `release`.

**The refusal was swallowed into exit 0.** The internal status-write handler
returns a successful transport carrying `status_write_success=false` when the
inner gate refuses, and the engine checked only the transport result. It
printed `release -> done`, exited 0, and left the row at `release` — while the
refusal narrative went to server-side stdout, where an https relay loses it.
The item looked closed out and was not.

## The decision

**Close-out failures are prevented where they are caused, and a refusal is
reported as a failure.**

1. **The lane's removal cannot blind the process.** Before the cleanup removes
   the worktree, every loaded package whose cached `__path__` points into it is
   repointed at the surviving checkout
   (`yoke_core.domain.worktree_import_reseat`). The helper is blind to package
   names: whatever the process happened to load out of the doomed directory is
   what needs repointing. It runs at the single site that deletes the lane, so
   there is no ordering for a caller to get wrong.

2. **The gate compares against the set of heads the merge boundary recorded**
   (`yoke_core.domain.qa_merging_identity.accepted_merging_shas`): the merge
   receipt's landing and merge commits, the newest head a passing `ci_run`
   proved green, the execution evidence a workflow may add, and the lane
   column. A run recorded at none of them predates the merge and is still
   refused, so the gate keeps its teeth while a legitimate two-tree merge
   settles. Both routes now write that receipt — the queue route did not
   before, which is why a queue landing had no local identity at all.

3. **A refused write is a failed write.** The handler carries the refusal text
   and code in its result payload, and `_update_item_direct` reports
   `status_write_success=false` as the failure it is. That engages the existing
   retry-and-verify path and makes the engine exit non-zero with the real
   reason instead of announcing a transition that did not happen.

## Why not the alternatives

**Cleanup last.** Moving the worktree removal after the terminal transition is
the structurally safest ordering and was the first candidate. It was rejected
because the removal lives inside the merge engine shared with epic-lane merges,
where the close-out is not one call away, and because the import hazard would
survive anywhere the engine still deletes a tree mid-process. Reseating fixes
the hazard itself rather than the one ordering that exposed it.

**A first-class `merged_sha` column.** A column is the natural home for a
single merge identity and is why it was rejected: the answer is a set, not a
value. It would also arrive unreadable — a control plane deployed before the
column cannot store what the merge that ships it needs to record.

**Re-running every requirement at the integrated head.** This is what the
operator did by hand to unstrand the items that motivated the work, and it
cannot be the contract: under a merge queue the combined head is only knowable
after the merge, so the requirement would be to re-verify a tree that has
already landed, on every member of every train.

## Consequences

- A queue-landed item carries the same landing identity a locally merged one
  does, and its close-out reads the same surfaces.
- The terminal transition accepts a passing run recorded at either the lane
  head or the integrated head, and no others.
- A refused done transition exits non-zero and prints why, over both
  transports.
- The reseat helper is a general defense: any operation that deletes a tree the
  process may be importing from can call it before doing so.
