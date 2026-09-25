# Dash phase 7 — record evidence and finish

## The merged close-out

Issue the merge-and-close-out command. Non-queue projects and an explicit
`--wait` finish inline; the default queue route follows the handoff in
[`merge.md`](merge.md). The operation resolves the touched files from the
branch itself, so no path list is needed. Dash close-out is evidence-gated on
this same command — pass `--result` and `--verification` even when the merge
queue already landed the branch. Do not substitute
`yoke lifecycle transition --to done`; that path cannot restore the work claim
the landing handoff retains.

```text
yoke merge item ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --json
```

The status the command reports is the pinned definition's, not a fixed `done`.
When the item's registered deployment flow still owes a delivery, the close-out
lands the item at that definition's release wait, keeps the lane and claim for
the later close-out, and parks this session on that wait with a concrete
deployment-wait reason; the envelope's `status` names that stage, the
`release_wait` block names the park, and this is a completed merge, not a
failure. **You stay the owner through delivery.** Do not release the claim and
do not end the session there: the outcome block prints `awaiting delivery`,
and the legs a worker mandate calls complete are not complete until the item
reaches `done`. Report what landed in your own output, say you are waiting on
delivery, and stop deliberately. If the block reports the park `unconfirmed`,
stamp it yourself so wake and recovery routing can find the delivery wait:

```text
yoke sessions touch --mode parked --reason "awaiting ITEM delivery: deployment run, then post-deploy validation and the done close-out"
```

The deployment wake re-enters you: a QA stage that needs your evidence, a
verdict on one you supplied, the notice that your own item-scoped QA is
accepted (the run may still be executing; other members' outstanding item QA
does not block you), or the notice that your run succeeded and the
wait is over — that last one fires only for the run that actually discharges
this item's delivery, so a stage run in a stage-and-production pair will not
call you. Re-run the same `yoke merge item` command with `--result` and
`--verification` then, and it finishes the close-out. Never poll the run.
A member that recorded `post_deploy_no_obligation` before it landed does
not get that wake: the same close-out runs without a session after its final
delivery on a flow with no shared gate, or when the completion run succeeds.
For a final member on a selected flow without run QA or run approval, accepted
or explicitly discharged final production item QA closes that member while the
run may still execute for siblings. Run QA or run approval holds every final
member through all item and shared gates and run success.
After an item QA acceptance wake, check whether your item reached done and
re-park only while it remains at release wait.

A run in ANOTHER project never calls you either, even when it deployed your
code. A flow stage may bind a second project's branch tip through
`input_bindings` and deploy that commit alongside its own candidate, so your
merged change can already be live before any run of yours exists. That deploys
the code; it does not discharge the item. Membership is same-project only, so
only a run on your own item's flow carries you, wakes you, and lets this
close-out finish. Keep waiting for that run — and when you report, say your
code may already be serving, so the reader does not read your open wait as an
unshipped change.

A stage that wants your evidence is run by naming that stage AND your item.
When you attached an item QA plan at verify, the stage has already resolved it
and `--plan` is refused there — a plan on a stage that already names its cases
materializes a second, duplicate set beside the ones it credits. `--plan`
belongs only to the wake that says the stage names no cases:

```text
yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P
```

That is the long, prod-touching step, so it runs under its own wrapper —
`yoke watch qa-plan`, not `yoke watch qa-case`, which wraps the narrower
`qa case run --requirement-id N` and refuses these flags.

Every QA stage credits only requirements bound to its own name — an
item-scoped one to the member too — so the run-wide form is refused rather
than recording a pass the stage ignores, and `yoke qa case run
--requirement-id N` credits that requirement's binding rather than the stage.
Depth: `yoke qa plan run --help` for the subject/scope matrix, `yoke merge
item --help` for the close-out routes. Materialization stamps the run's own
deployed target onto the cases, so a plan authored before this release still
verifies it. A deployment case is bound to the candidate the run deployed, not
to your lane: run it from a checkout at that revision and no flag is needed;
`--allow-tree-mismatch` declares the case reads nothing from the checkout.

**Any prompt that wakes you clears the park**, including one that does not
finish the item. The close-out re-stamps it for you when it refuses, but a
wake you handled some other way does not: whenever you go quiet still short
of `done`, re-park first with the command above. The active work claim retains
the session through idle sweeps, process exit, and restart; the park records
the wait for wake and recovery routing. When the resolved flow discharges delivery at
the merge — a flow with no target tier — the close-out transitions through
every declared stage to `done`, so the release stage runs its own gates on the
way. Read the `[close-out]` block and the envelope's `status` rather than
assuming either outcome, and never start a deployment run to move an item that
its own flow says needs none.

Add `--no-changes` for a genuine no-change result. When the merge is already
recorded and only the close-out remains — after a deployment run, after
approval, or after a queue landing that has not reached `done` — re-run the
same merge command with `--result` and `--verification`. It restores the work
claim close-out needs and records evidence if the merge identity is not yet on
the item. Do not hand-run `lifecycle.transition --to done` for Dash close-out.

A delivery-required item finishes through that same command. Re-entering at
the release wait once the deploy has succeeded IS the done ceremony: the
close-out asks whether a succeeded run of the item's selected flow delivered
it, and performs the ceremony when the answer is yes. So there is no second
command to reach for and no usher leg to jump to — if the transition still
refuses, read the named reason rather than switching routes.

A queue landing's merge-group proof is recorded when the train lands, and the
close-out at the deployment wake reads that record rather than asking GitHub
again — so parking across a release wait costs the evidence nothing. When no
record exists and the derivation itself fails, read whether the refusal says
a retry can help: a provider that failed to answer is worth re-running, while
an anchored search that completed and found no run returns the same answer
forever and says so. Do not answer the second kind by re-running the command,
and do not reach for `done-transition --skip-deploy` — that flag records
delivery as out-of-band, and the done engine now refuses it outright when the
item's own selected flow already delivered it.

Re-entry converges only when the current lane candidate is the recorded landing
identity, a fast-forward onto that merge — including a squash whose original
head is not an ancestor of the base — or a lane that adds nothing to the base
branch at all. That last one covers both a rebase after a landing and a lane
whose commits reached the base under a companion item's landing: it is asked
by merging the lane into the base and comparing the result to the base's own
tree, so foreign shas and lane-side merges do not defeat it, and a lane still
carrying anything — a deletion included — still takes the candidate merge
path. A merge-queue `landed_at` / PR record is not that proof by
itself: close-out reuses it only when Git containment (or a lane that adds
nothing) shows the current candidate already landed. An earlier
landing plus later uncontained commits takes the candidate merge path — also
from a release stage entered by a false close-out — and does not erase
receipts. Unverifiable containment refuses rather than succeeding. This is
installed-client merge-boundary code; a serving rollout is not required. New
commits after a genuine landing: same-item correction continues through a
declared release wait on the same item and lane — re-verify, review, and run
the governed merge again, then a fresh selected-flow delivery. Do not
prescribe a stage change. The mismatch refusal preserves the lane when the
item is already closed out, or when the pinned workflow declares no release
wait. Do not reset unlanded corrections as recovery.
The command does not clean the lane or declare those commits delivered.

## A steering rework request

Steering does not gate your landing; it vets the work after it lands and
before the item is admitted to a release. When that vetting finds a problem,
steering moves the item back to `implementing` and names what to correct.
That is a rework leg on this same item: correct it in the same lane,
re-verify, re-land through the same `yoke merge item` command, and re-enter
the release wait. Evidence recorded against the earlier revision does not
carry over to the corrected one, so the verification gate runs again. Do not
file a new item, and do not close this one out on the superseded evidence.
Escalate only when you cannot make the correction, naming what blocks you.

## Approval, claim release, and the steering report

When approval-on-done is selected, the terminal transition creates the owner
decision request without moving the item. Let an authorized owner resolve it,
then retry the transition.

A merge refused for an uncleared merge candidate never got as far as a
landing, so nothing here has happened yet. The refusal names the open
decision request an authorized reviewer answers; report it to the steering
seat with that request id and stop, rather than re-running the merge. When
the clearance lands, re-run the same `yoke merge item` command — but commit
nothing in between, because a new commit is a new candidate and needs its
own review.

A successful standalone merge (or the terminal transition it drives)
may already release the item work claim and remove the
registered Dash worktree lane, then sweeps lanes earlier landings on this
machine preserved: the
envelope's `lane_sweep` names what it removed and kept (with the reason), and a
refusal on the item's own lane is recorded as a `LandedLanePreserved` event.
Only release when a claim remains AND the item is finished — a terminal status,
or an exit before merge (including escalation). A claim retained at a release
wait is not a leftover to tidy up; releasing it there is the abandonment this
step exists to prevent:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

Skip that call when merge or `done` already released the claim, and skip it
entirely while the item sits at a release wait. Do not treat an
already-released claim as a close-out failure.

When a report to the steering seat is still owed, send it BEFORE that release.
`yoke say --steering` addresses the seat covering the item you hold, and falls
back to the item you last held in this session, so the report resolves either
side of close-out; sending first keeps the live claim as the address. One
terminal report per work leg reaches the seat once, so a reworded retry of the
same completion deduplicates rather than arriving twice, and a send answering
`Collapsed into an earlier message` did not deliver the body you just sent. A
completion you are resumed to do is its own leg and is delivered, whether or
not the resume hands you a fresh claim; never release an unfinished lane merely
to be heard. Ending a turn sends no Fleet message; every worker uses this
deliberate route regardless of launch origin. A close-out that stopped at a
release wait owes no terminal report yet: the leg completes at `done`, and
reporting early is how an item with a live owner gets read as finished.

## Surface this session's guardrail denials

After evidence is recorded, report this episode's PreToolUse denials. Close-out
reports; it does not block. An empty result is silence: say nothing extra.

Read `session_id` from registered `sessions.identity`
(`yoke sessions identity`); do not invent it. `--session` filters
`events.session_id`. Do not pass `--session-id` — that flag overrides caller
identity. Then run registered `events.query.run`:

```text
yoke events query --session SESSION_ID --event-name HarnessToolCallDenied --current-episode --json
```

When `result.elided_prior_episode_rows` is present, this session crossed an
episode boundary mid-Dash — a sleep, a reload, a brief disconnect — and that
many denials sit in the previous episode. Re-run the same query without
`--current-episode` and report the whole session's denials. An empty `rows`
beside a non-zero count is not a clean run.

When `result.rows` is non-empty, print a short list of each row's `check_id`
and `command_snippet` from `envelope.context.detail` (parse `envelope` when it
is a JSON string). File a field-note for any denial not already recorded, or
state why none is warranted:

```text
yoke ouroboros field-note append --kind observation --evidence '...'
```

Do not correlate denials to field-notes in storage. Visibility is the entire
ask.

## Laneless and evidence-only close-out

Two closes record no merge SHA, and both are first-class rather than a bypass.

A genuine no-changes finding edited nothing. After a skipped lane, do not run
CI, merge, or a deployment unless explicit policy still requires it:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --no-changes --json
```

Then move the Dash through `reviewing-implementation` to `done` on that
attestation. `yoke merge item --no-changes` is only for a lane that already
exists.

An item whose pinned workflow delivers merge-free — `worktrees=none`,
`delivery=merge_free`, the floor Task shape — did change things, and names them
as the observed changes:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --path notes/readme.txt --json
```

Do not reach for `--no-changes` to skip the SHAs on a laneless item that did
change files: the floor rung comes from the item's own delivery policy, so the
SHAs are already optional and `--no-changes` would record the wrong fact. A
merging workflow that omits its SHAs is refused, and the refusal names both
routes.

Task items have no `reviewing-implementation` stage. Close `implementing` →
`done` once the attestation is recorded:

```text
yoke lifecycle transition ITEM --from implementing --to done \
  --reason "Floor attestation recorded"
```

Outward-action approval gating is a future seam; do not invent one here.
