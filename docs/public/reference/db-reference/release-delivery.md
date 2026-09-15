# DB Reference — Release delivery: QA authorities, verdicts, notices

How a merged item's release is verified and announced, across the tables
[events-and-deployments.md](events-and-deployments.md) defines:
`deployment_runs`, `deployment_run_items`, `deployment_run_qa`,
`deployment_stage_receipts`, and the `qa_requirements` / `qa_runs` rows a
scoped stage settles through. Those table schemas stay there; what lives
here is the behavior that reads and writes across them.

## What this runtime actually serves

Two independent axes decide whether a deployment flow definition can be
activated, assigned and started, and both are reported rather than
assumed.

`deployment_flow_policy.CURRENT_EXECUTION_SCHEMA_VERSION` is the richest
definition *vocabulary* this runtime executes. It serves the release
schema: ordered per-stage execution, scoped QA materialization and
gating, stage receipts carrying observed evidence, the wait and verdict
wakes, the configured result notification, and release-to-done
acceptance.

Target *kinds* are the other axis and the schema version promises
nothing about them. A QA stage reads its target from an earlier stage's
receipt, so a kind with no registered receipt producer cannot be
executed however complete the rest of the runtime is —
`deployment_flow_target_support.unsupported_stage_target_kinds` names
them, and the same gates the schema version guards refuse them:
activating, updating an active definition, assigning, and starting. That
is why the refusal arrives before a run exists rather than mid-run after
earlier stages have already deployed; the producer's own refusal stays
as defense-in-depth.

`deployment_flows.validate-definition` answers on both axes —
`execution_supported` is true only when the vocabulary is served AND
every QA target this definition names has a producer, with
`unsupported_target_kinds` naming the gap. A definition can still be
stored and kept disabled while its producer is absent, which is what
lets configuration land ahead of runtime.

Target kinds are one axis of that answer and identity provability is the
other, because supporting a kind is not the same as being able to
observe one. A QA stage reads its target from an earlier stage's
receipt, and that receipt is evidence only if the producing step runner
returned a *verified* candidate identity rather than a diagnostic
string. `IDENTITY_PROVING_STEP_RUNNERS` names the runners that do;
today that is the Yoke core health check alone, which asserts the served
`build` against the run's pinned image tag over Yoke's own health
contract. That is a Yoke-core-shaped proof, not a generic one: a project
deploying its own environment through its own workflow has a perfectly
valid `persistent_environment` target behind a runner that reports what
the workflow did rather than what the environment now serves.

`RUNNER_VERIFIED_TARGET_KINDS` names the kinds that take their identity
from the runner. A kind whose producer reads the target back itself is
deliberately excluded — the runner that deployed a preview never needed
to prove anything — which keeps the two axes independent. A QA stage in
that intersection behind a non-proving runner is refused at the same
gates, reported as `unprovable_qa_identity_stages`, and refused again
before dispatch so a definition activated before that gate existed stops
before it changes a real environment rather than after.

Registering a producer is therefore the whole act of widening the
boundary: `RECEIPT_PRODUCERS` gains an entry, `SUPPORTED_TARGET_KINDS`
derives from its keys, and these gates stop refusing that kind.

## Release-to-done reads both QA authorities again

A succeeded run is not by itself proof that an attached item may close.
An acceptance can be rejected by a human after the run finished, a
replacement producer receipt can retarget a stage so the earlier
acceptance no longer answers for it, and an operator can carry an item
toward done on recorded evidence rather than a live pass
(`--skip-deploy`, a resume, a run left at an unexpected status). So the
release-to-done guard re-reads both authorities for the item it is
closing:

- `deployment_run_qa`, through `done_transition.run_blocking_qa`.
- the pinned scoped per-stage acceptance, through
  `done_transition.run_stage_qa_acceptance` — the item's own
  item-scoped stages plus every run-scoped stage. Another member's
  outstanding item-scoped QA is that member's gate, not this item's.

Neither is a superset of the other: a legacy definition has no scoped
stages, and a scoped stage deliberately writes no `deployment_run_qa`
row. An unreadable read raises rather than reporting a clear gate, and
a universe whose schema predates the scoped vocabulary reports nothing
owed instead of failing.

Owners: `yoke_core.engines.done_transition_run_qa_gates` (the guard),
`yoke_core.domain.deployment_qa_run_acceptance` (the per-item read),
`yoke_core.domain.deployment_qa_stage_acceptance` (the shared
read-only acceptance ladder the active-stage gate settles).

## A human verdict reaches the agent that parked for it

A stage whose verdict policy requires a human opens a review request and
waits, and the agent that supplied the evidence parks. Resolving a
`qa_needs_review` request whose requirement is a deployment-stage subject
sends one notice to the recipient the wait itself addressed: the member's
claim holder or the project's steering seat, or the deploy-lock driver for
a run-scoped stage. It names the run, stage, subject, outcome and the next
step — an approval releases the parked agent, a rejection hands it work, a
waiver discharges the obligation. Sent after the resolution commits and
degrading to a warning when undeliverable, because the verdict is the
durable outcome; a requirement that is not a deployment-stage subject
notifies nobody. Owner: `yoke_core.domain.deployment_qa_verdict_notice`.

## A caseless QA stage waits rather than failing

A stage that names no cases is the ordinary shape, not a
misconfiguration: the agent responsible for the subject chooses or
creates the evidence. Materialization refuses when nothing is pinned,
admitted or agent-selected, and that refusal is the agent's cue — so it
carries its own exception type and the dispatch treats it as a durable
wait, adding the subject to the waiting set and waking whoever can end
it (the member's claim holder at item scope, the release's deploy-lock
driver at run scope).

Every other materialization refusal still fails the stage. An invalid
pinned plan, an unresolvable target identity and a permission denial do
not become truer by waiting, and dressing them as patience would strand
a release behind a definition nobody is going to fix. A definition
pinning a plan that does not exist cannot even be frozen into a run —
composition freeze refuses it — so it never reaches the dispatch to be
misread, which is why only one condition needs classifying there.

## A settled QA stage result reaches its configured audience

A release has three notification surfaces and they are deliberately
different. The stage-wait and human-verdict notices address SESSIONS —
the agent that owes the work, or the one parked for a decision — because
each asks somebody to act. This one addresses PEOPLE through the actor
Inbox and asks for nothing: when a QA stage settles, it reports what was
decided to whoever the flow said should hear it.

Audience comes from the stage's own `notification` policy, which the
flow definition already validates and which carries no ANY/ALL mode by
construction: `roles` naming project role holders, `actors` naming
members outright, and `item_owners` meaning the owners of the items the
result covers. The audience is the union. An item owner who is also in
it legitimately receives this notice AND the separate item-done notice —
different events about different things, each with its own key, never
folded together.

Only a settled result is reported: passed, or rejected. A stage still
waiting is not one, and reporting it would duplicate the wake that
already addressed the agent. A stage that configured no notification, or
one whose audience resolves to nobody, reports that rather than inventing
a recipient. Passed and rejected carry separate keys, so a later
rejection is its own event rather than a replacement, and the pinned
target identity is part of the key so a distinct attempt reports
distinctly. Reporting is best effort: the QA answer is the durable
outcome, so a failure to report degrades to a printed warning and never
changes the stage verdict.

Owners: `yoke_core.domain.deployment_qa_result_notice`, reported from the
pipeline's own QA-stage dispatch;
`yoke_core.domain.deployment_item_owner` resolves an item's owning member
for both this surface and the item-done notice.

## Done announces the delivery to the item's owner

Reaching done for a delivery-carrying item sends its OWNER one
informational notice naming the outcome, the destination, the candidate
revision, and the run whose evidence backs it. The owner is the human
member `items.owner` names, reached through the actor-addressed Fleet
path — the Inbox surface a person reads. It is deliberately not the
session holding the item's work claim: that is an agent, agents are
already woken for the QA stages they owe work on, and a notice that
redirects to whichever agent holds the claim tells the wrong party while
looking like it worked. An item whose owner does not resolve to a human
organization member reports that and sends nothing.

Nothing reads the notice: no decision, nothing to acknowledge, no gate.
The QA-result notice is a separate event with its own key and its own
recipient, so an owner who is also a reviewer legitimately receives both.

The destination named is the one the run was observed to deliver to —
the newest ready `deployment_stage_receipts.target_name` — rather than
the environment the run was configured to aim at, because a journey with
more than one environment stage aims at one and reaches each; the
configured target answers only when nothing observed one, and the target
tier only when neither does.

An item with no succeeded run has no destination to name and is silent,
as is one whose run failed or was cancelled. "Once at final completion"
needs no separate guard: done happens once, the key is the item plus the
run that delivered, and a progress-delivery member does not reach done
from the run that carried it. Delivery failure is reported by the
closeout and stays retryable — it never reverses a done that already
committed, and the closeout runs only after that commit. Owners:
`yoke_core.domain.deployment_delivery_done_notice` and the registered
`done_transition.delivery_done_notice`, which the client-side engine
relays to because sending is a control-plane write.
