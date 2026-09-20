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
   receipt's landing and merge commits, the passing ``ci_run`` identities
   (PR-entry head and train receipt, not only the newest row), the execution
   evidence a workflow may add, and the lane column. A later train receipt
   must not displace the PR-entry SHA the item's own case verified. When the
   train receipt names this merge, passing blocking runs are covered by it.
   A run recorded at none of those predates the merge and is still refused.
   Both routes write that receipt — the queue route did not before, which is
   why a queue landing had no local identity at all.

3. **A refused write is a failed write.** The handler carries the refusal text
   and code in its result payload, and `_update_item_direct` reports
   `status_write_success=false` as the failure it is. That engages the existing
   retry-and-verify path and makes the engine exit non-zero with the real
   reason instead of announcing a transition that did not happen.

### The mirror case: a completion reported as a failure

Mechanism 3 has an inverse that showed up later. The merge result envelope
answered `evidence_recorded` from the return of one write attempt, so a relayed
evidence write that failed and then succeeded reported `false` beside a record
that existed; and because the terminal transition releases the item's work
claim, re-entering the landing afterwards hit the claim precondition and refused
with "no active claim" on an item already merged, closed out, and `done`. Both
sent an operator to repair state that was already correct.

So the envelope reports the record's own state
(`yoke_core.domain.standalone_item_merge_evidence`). A refused write is
confirmed against the persisted record, and forgiven only when that record
carries this merge's identity — a row from an earlier landing answers for that
landing, not this one. A claim refusal on an item that is terminal *and* holds
an evidence record converges on a completed envelope built from the record's own
facts, and carries no `published` or `target` key, because neither is a fact the
record holds. An item short of terminal still refuses: it has work left.

### The mirror case again: a completion nobody could read

Reporting a completion as a completion is not the same as making it visible.
The envelope became truthful and stayed a block of JSON, and the command that
prints it is also the only surface that reads live close-out gate state — it
refuses with the reason, and it requires `--result` and `--verification` to
run at all. So an operator asking "is it unblocked yet?" re-runs it, and the
run that finally passes is the run that writes: it replaced a full account of
a merge with the word `probe`, released the work claim, and moved the item to
`done`, looking on the terminal exactly like the four refusals before it.

So every exit names its own outcome for a person
(`yoke_core.domain.standalone_item_merge_close_out_report`). One `[close-out]`
block goes to stderr beside the phase markers, stdout stays the envelope, and
the block's first line is the verdict: closed, already closed, landing
pending, or not closed with its blocker. Under it go only the effects that
run established — that the evidence record now carries this invocation's
summaries, and what a live holder read says about the work claim. The claim
line is read rather than assumed, because "the terminal transition releases
the claim" is what usually happens, not what happened; an unreadable holder
is named `unconfirmed` and never reported as a release.

That read is contained rather than merely attempted, and the containment is
the point: it runs after the merge has landed and the item is closed out, so
an unreachable relay, a holder shape the running build does not expect, or an
unresolvable ambient identity must not raise out of the line whose job is to
say the close-out succeeded. The block that exists to stop a completion from
looking like a refusal would otherwise be able to turn one into a refusal.

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

## The merge-only item that could not finish

A fourth mechanism produced the same wreckage from the opposite direction, and
it needed no failure at all to fire.

Whether an item still owes a deployment is the registered flow's answer: a
flow whose `target_tier` is null discharges delivery at the merge, which is
what every project's internal flow is for. The close-out read that verdict and
targeted `done` directly. But a `release_stage` pinned definition declares a
strictly linear graph — `... -> reviewing-implementation -> release -> done` —
with no edge that skips its release wait, and the merge boundary is edge-checked
because it names no status-write source. So the merge landed, evidence was
recorded, and the terminal transition was refused for a transition the
definition does not declare. Advancing the one declared stage the refusal
named then hit the second wall: `release -> done` needs the done-transition
ceremony nonce, whose only holder is the deploy ceremony this item has no
deployment to run. A close-out that read "delivery discharged" could not
discharge it.

**Delivery clearance decides the whole route before the first transition, and
a merge that is the whole of an item's delivery asserts the ceremony it
performed.** `standalone_item_merge_release_status.close_out_route` returns the
ordered declared stages to walk plus whether delivery is discharged, and
`standalone_item_merge_terminal.transition_to_done` transitions once per
declared edge. A merge-only item walks `release -> done`, so the release
stage runs its own gates — its QA verification, its path-claim boundary —
rather than being skipped by a jump the definition never declared, and only
the terminal step carries `done_nonce_verified`, exactly as the deploy engine
asserts it after running its ceremony. An item whose flow names a real target
tier is never marked discharged: its route stops at the release wait, and the
nonce gate keeps holding `done` for the deploy that owes it.

Resolving the route up front is what keeps the two facts from disagreeing
again. Deciding per step would have to re-ask "is delivery clear?" from the
release stage, where the honest answer for a waiting item and a discharged one
is the same stage id; the difference is the flow's verdict, which only the
first reading still has. So the clearance read leads even when the item is
already standing at the release wait — that is the re-entry case, and the flow
still owns the answer there. The one status that asks nothing is the terminal
one: an item already closed out owes its lane a retirement, not a route, and
an unconfigured flow must not turn that into a refusal on finished work.

### Why not the alternatives

**Mint the nonce for any close-out.** The nonce exists so a bare command line
cannot write `status=done`. Asserting it whenever the merge boundary targets
the terminal stage would also release every delivery-required item waiting at
its release stage, because that item's route targets `done` too — the nonce
gate is what holds it there today. Binding the assertion to the flow's
merge-only verdict is the difference between "this path ran the ceremony" and
"this path skips ceremonies".

**Land at the release wait and stop.** Correct for an item that owes a deploy,
and a dead end for one that does not: nothing would ever come back for it, so
the operator finishes by hand — the wreckage this document exists to prevent.

**Declare a `reviewing-implementation -> done` edge for merge-only pins.** A
pinned definition is immutable and a flow is chosen per item, so the shortcut
would have to exist on every release-bearing definition and be legal for items
that must not take it. The stage is not the thing to remove; running its gates
on the way through is the point.

## Consequences

- A queue-landed item carries the same landing identity a locally merged one
  does, and its close-out reads the same surfaces.
- The terminal transition accepts a passing run recorded at the lane head,
  the CI-verified PR-entry head, or the integrated head. When a merge-queue
  batch receipt names this item's merge identity, that train run is the
  covering verdict: passing blocking runs are not stale against a SHA the
  queue rewrote, and a per-item re-verdict at the combined head is not
  required. A run recorded at none of those predates the merge and is still
  refused.
- A refused done transition exits non-zero and prints why, over both
  transports.
- A merge whose close-out completed reports as completed, whether the reporting
  process is the one that finished it or a later re-entry.
- The reseat helper is a general defense: any operation that deletes a tree the
  process may be importing from can call it before doing so.
- Whichever of those outcomes a run reaches, it says so in one block a person
  can read, and claims no effect it did not confirm.
- An item whose registered flow discharges delivery at the merge reaches
  `done` through its own declared stages, with no deployment run started for
  bookkeeping and no hand-written status.
- An item whose flow names a real target tier still stops at its release wait
  and still needs the deploy ceremony to reach `done`.
- A step that refuses mid-route stops the walk and reports that refusal; the
  item stands at the last stage it legally reached, and re-running the same
  merge command resumes from there.

## Reporting the wait as a wait

The nonce gate holding a delivery-required item at its release stage was doing
its job, but the owner never learned that. A close-out re-entered at the
release wait read the delivery evidence, and three different answers reached
one line of code: delivered, definitely not delivered, and could-not-read. The
unread answer refused by name. The other two both routed to the terminal
stage, so an item whose deploy had not happened walked into the done ceremony
it could not perform and came back with "missing done-transition ceremony
nonce. Close it out through /yoke dash PREFIX-N" — naming the command that had
just run, about a delivery nobody had mentioned. Two workers were sent hunting
a defect that was not there.

Every fact the owner needed was already in hand at that decision: the flow the
clearance resolved, the run the evidence ladder had just read and the status it
sits at, and the ladder's own reason and recovery. The route was discarding
them and substituting a ceremony error.

**A definite "not delivered" is an answer, not a failed read.** It keeps the
item where it stands, carries the named wait, and re-parks the owner, exactly
as entering that wait the first time does. It is deliberately not reported
through the unread branch's refusal: the clearance did resolve — to "not yet" —
and reusing "delivery clearance could not be resolved" for it would be the same
trade the nonce error made, a convenient refusal in place of the honest one.

- A close-out that finds its delivery still outstanding exits 0 as a completed
  merge and an unfinished item, names the flow and the run it is waiting on,
  keeps the lane and the claim, and re-stamps the park the wake had cleared.
- The delivery-evidence read carries the run it read on its not-delivered
  answer, so a run in any status — not only one worth retrying — is named.
- A delivery that could not be read still refuses by name, and a delivery that
  happened still walks the declared stages to `done`.
