# Dash — record evidence and finish

## Merged close-out and delivery custody

Use the same evidence-gated merge command, even after a queue landing:

```text
yoke merge item ITEM --result "<result>" --verification "<checks/evidence>" --json
```

It resolves actual touched files and merge identity. Do not substitute a
terminal scalar/lifecycle write for a landed Dash. Read the pinned status and
[close-out] block, not exit0 alone.

If delivery is still owed, the command retains the claim and registered Dash worktree lane,
lands at the declared release wait and parks this session.
You stay the owner through delivery. Do not release the claim and do not end
the session there; no early DONE or terminal steering report.
Read what the item owes (exact stage/member requirements) and verified wake
authority, and report them. If park is unconfirmed, stamp it:

```text
yoke sessions touch --mode parked --reason "awaiting ITEM delivery: deployment run, then post-deploy validation and the done close-out"
```

Any prompt that wakes you clears the park. If the item remains short of done
and you go quiet, re-park first with the command above. The active work claim
retains the session through idle sweeps; never release the unfinished claim. An operator-wake desktop needs
its operator/steering seat to reenter; do not promise a native wake.
An item owing nothing closes on actual delivery without reentry.

Only completion authority discharges delivery: the item's selected flow,
or another project's run recording this project's bound source and carrying
the item as a member. Carried code alone, a same-project unrelated flow or a
failed run does not close it. Bound code may already serve while closure
waits; say only what evidence proves. A close-out refusal keeps the run
executing/settling and claim/lane intact for named repair.

With no shared run QA/approval, accepted or discharged final production item
QA may close a final member while siblings still run, provided no run-bound
blocking obligation remains. Shared run QA/approval holds all final members
through their item cases, shared gates and success. An item still owing stage
QA remains open; production acceptance cannot hide it.

Native wakes cover this item's outstanding QA, review result, acceptance or
its actual completion-run success; a supplemental stage run does not claim
final completion. Check actual done after acceptance, otherwise repark.
Ordinary success stamps delivery itself, so do not rerun merely to duplicate
a record. When close-out is still required, resume the same merge with
result/verification; it restores needed claim/evidence. There is no separate
Usher leg or done-transition skip-deploy shortcut.

## Exact deployment QA subject and review

Run the stage and member together:

```text
yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P
```

The attached plan is already resolved. Do not substitute --plan except when
the wake explicitly names no cases, or for the sanctioned correction-only
replacement of failed admitted cases with every CASE_KEY=FAILED_REQUIREMENT_ID.
An unrelated replacement adds duplicate obligations.
The long step uses qa-plan; qa-case wraps only a requirement and refuses these
subject flags. An item stage credits exact stage/member binding, never a
run-wide pass. Requirement-case execution credits its stored binding and does
not substitute for stage execution.

Exit12 awaiting_agent_review/review_status=pending is capture only, no pass.
Dispatch the returned independent review_bundle.dispatch and submit its full
batch with the exact returned command. Own complete/record-verdict is refused.
If another session owns review, repark until accepted evidence exists.

Deployment Command cases execute the pinned deployed candidate in disposable
trees; main/lane movement does not change their source. No checkout-path
override is needed. allow-tree-mismatch means the case reads no checkout.
command-ci refuses deployed binding as deployment_ci_candidate_unverified.
Use Command for that pinned proof. Read qa.plan.run help for scope/methods.

## Convergent landing and correction

A no-target flow walks every declared gate to done; do not invent a deployment.
No-changes flag is only for a grounded no-edit outcome.

The queue's durable merge-group proof survives release wait. If missing
derivation is a provider read error, retry the named route; an anchored complete
search finding no run will repeat forever and needs its repair.
Do not use skip-deploy to record an already selected-flow delivery out of band.

Resume converges only when the current lane is the recorded landing, a
fast-forward/squash-contained candidate, or adds no tree change to base.
The no-change containment check accounts for foreign SHAs, lane merges and
deletions. PR/landed_at alone is not current-candidate proof.
Unverifiable containment refuses. Later uncontained commits take a new
candidate landing, preserving receipts, even after a false release close-out.
A genuine same-item correction stays on this lane/item through a declared
release wait: reverify, independent candidate review where selected, remerge
and fresh selected-flow delivery. No prescribed stage reset or discard.
Already-closed/no-release-wait mismatch preserves the lane and names refusal;
the command does not clean or declare corrections delivered.

For steering-requested rework, refresh the exact pin. Verify REWORK_STAGE
exists, precedes LIVE_STAGE and belongs to Dash's interval.
Backward rework need not have a forward transition edge; ordinary claim,
frozen-item, source and target checks remain:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to REWORK_STAGE --reason "steering rework: <correction>"
```

Correct the same item, rerun evidence, re-land, reenter wait. Old proof does not
cover the new revision. Steering vets after landing/before release admission;
its lack of work claim does not authorize it to make the worker's rework
transition. A refusal reports its real recovery; no new item.

## Approval, claim release and terminal report

Approval-on-done creates the authorized owner's request without transition.
Wait for that decision, then resume. Uncleared candidate review never landed:
report its exact request, wait, and rerun only after independent clearance
without intervening commits.

Successful merge/done may already release the item work claim and sweep its
lane; read lane_sweep kept/removed reasons and LandedLanePreserved evidence.
Only release when a claim remains AND the item is finished, or on an actual
premerge exit. Skip an already-released claim and skip it entirely while the item sits at a release wait.

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

A terminal report still owed goes to yoke say --steering before release.
It addresses the covering role from held/last-held work, not a copied seat
session. One terminal report per leg deduplicates; Collapsed into an earlier
message means the new body was discarded. A resumed completion is its own
leg. Never release unfinished work merely to be heard.
Ending a turn sends no Fleet mail; release wait owes no terminal report yet.

## Surface this session's guardrail denials

Reporting does not block close-out. Empty means say nothing extra.
Read sessions.identity through yoke sessions identity; --session filters
event ownership while --session-id would override caller identity.
Use events.query.run:

```text
yoke events query --session SESSION_ID --event-name HarnessToolCallDenied --current-episode --json
```

If elided_prior_episode_rows is nonzero, rerun without current-episode and
report the entire session; empty current rows is not a clean history.
List check_id and command_snippet from envelope.context.detail (parse string
envelope). File an immediate field-note for unrecorded denials or state why
none is warranted. Do not correlate denials to field-notes in storage.

## Laneless and no-change close-out

A genuine no-change finding after skipped preparation records:

```text
yoke direct-workflow dash evidence ITEM --result "<finding>" --verification "<observed proof>" --no-changes --json
```

No fabricated SHA, CI, merge or deployment; explicit selected gates remain.
Walk the exact pin one unique declared forward edge at a time, refreshing
status/version and verifying the live Dash binding before each step, until a
terminal_stage_id. Missing/ambiguous edge refuses workflow_next_stage_ambiguous.
A binding boundary is a fresh handoff, not permission to cross it.

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Laneless attestation recorded; advancing the declared stage"
```

No-change with an existing lane uses merge item --no-changes, not this walk.
A merge-free/none-policy item that changed files records those paths instead:

```text
yoke direct-workflow dash evidence ITEM --result "<result>" --verification "<observed proof>" --path notes/readme.txt --json
```

Its floor policy makes SHAs optional; no-changes would assert a false fact.
A merging workflow without identity refuses and names both routes.
Use the same pinned walk after honest evidence. Delivery waits for a run
with completion authority; success normally closes it.
Do not invent future outward-action approval gating.
