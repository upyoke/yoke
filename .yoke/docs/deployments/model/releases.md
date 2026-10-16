# DB Reference — Release delivery: QA authorities, verdicts, notices

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Release authorities
<!-- /yoke:breadcrumbs -->

Read release verification across [runs](runs.md), [stage receipts](stage-receipts.md),
[members and QA](run-members.md) and [QA requirements](../../reference/db-reference/qa-and-sessions.md).
Those pages own the table schemas; this page explains how release checks consume
them. [Release notices](release-notices.md) covers caseless QA, settled results and
owner delivery announcements.

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

Target *kinds* are independent of schema vocabulary. A QA stage reads an
earlier stage's receipt; a kind without a registered producer cannot execute.
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

Identity provability is a separate constraint: a receipt must verify which
candidate the target serves. Either of two sources supplies it.

The first is the environment itself, and it is the project-agnostic one.
When the project configures an identity path on its `health-endpoint`
capability, the producer reads the revision back off the environment's
own registered `environments.url` at that path and the answer is the
observation — whatever deployed the environment. So a project that
deploys through its own workflow has a provable `persistent_environment`
target without Yoke-shaped health semantics.

The second applies only when no such path is configured: the producing
step runner's own verified candidate identity.
`IDENTITY_PROVING_STEP_RUNNERS` names the runners that return one, which
today is the Yoke core health check alone, asserting the served `build`
against the run's pinned image tag over Yoke's own health contract. That
is a Yoke-core-shaped proof, so it is the fallback rather than the rule,
and it keeps every definition that predates the configured path working
unchanged.

`RUNNER_VERIFIED_TARGET_KINDS` names the kinds that take their identity
from the runner when they have no readback of their own. A kind whose
producer reads the target back itself is deliberately excluded — the
runner that deployed a preview never needed to prove anything — which
keeps the two axes independent. A QA stage in that intersection, behind a
non-proving runner *and* with no configured identity path, is refused at
the same gates, reported as `unprovable_qa_identity_stages`, and refused
again before dispatch so a definition activated before that gate existed
stops before it changes a real environment rather than after.

## Asking a deployed environment which revision it serves

The configured proof is one reader, `served_revision_probe`, shared with
the preview freshness check rather than duplicated per target class. It
GETs the path, follows redirects only while they stay on the origin it
was given, and accepts only a verified `200` whose trimmed body is one
full 40-character revision equal to the candidate. An abbreviation, a
placeholder such as `unknown`, an error page, a non-200 carrying the
right body, and a redirect off the origin are each reported as what
could not be verified — `unreachable`, `malformed`, `mismatch` — rather
than as a match, and the response format is deliberately not negotiable:
plain text is the contract the one live consumer already serves.

Neither half of the question comes from the machine that asks it. The
origin is the environment's own registered url and the path is project
capability authority, both resolved server-side beside the run by
`deployment_target_identity_config.run_target_identity` and handed to the
release driver, which runs the candidate build and probes over the
network but supplies neither value. The origin is selected by the same
environment name the receipt records (`identity_origin_for`), so a
sibling environment's host can never answer for the environment under
test, and the consumer's own requirement that the receipt's
`target_name` equal the QA stage's declared environment binds the
evidence to the target QA actually runs against.

Which capability carries the path is a target-class distinction, not a
naming one: `health-endpoint.identity_path` is persistent authority and
`ephemeral-env.identity_path` is preview authority, because a preview and
a long-lived environment have different origins and one is no authority
over the other. Both refuse a configured value carrying its own scheme
or host through the same rule
(`served_revision_probe.origin_relative_path_error`), at the point the
value is set rather than where it is read.

Absence and failure stay different answers throughout. Most projects
publish no such endpoint, which is an answer — the runner-verified
fallback applies and nothing is refused. A capability that cannot be
*read* is not evidence of absence, so it refuses activation and refuses
before dispatch, naming the read that failed, rather than reporting
"unconfigured" and letting an unprovable definition through on the
strength of a failed lookup.

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

Member settlement and the terminal done gate also read blocking `post_deploy` requirements on the run.
Legacy schema-1 runs credit their shared run-wide requirements without source keys;
scoped runs keep exact private-member or attached shared-plan binding. Failing or unanswered requirements block;
supersession transfers the obligation to the successor requirement.

Owners: `yoke_core.engines.done_transition_run_qa_gates` (the guard),
`yoke_core.domain.deployment_qa_run_acceptance` (the per-item read),
`yoke_core.domain.deployment_qa_stage_acceptance` (the shared
read-only acceptance ladder the active-stage gate settles).

## An accepted item-scoped QA wakes that member

Acceptance and its wake address the member independently of the batch.

Only blocking aggregate requirements demand evidence-linked verdicts. Adding a
blocking post-deploy requirement retracts the item's prior no-obligation
declaration, retaining its reason and retraction history; non-blocking and
pre-deploy requirements leave that declaration live.
When an item-scoped stage subject becomes accepted or is discharged by an
explicit `post_deploy_no_obligation` or a waiver-backed item declaration,
with no outstanding run-bound blocking obligation, and
`deployment_qa_run_acceptance.item_qa_acceptance_blockers` is empty for
that member, a final production member on a selected flow without run QA or run approval
closes independently even while sibling item QA holds the run open. The
same final-delivery, evidence, and done gates still apply. If automatic
close-out refuses, the member's release-wait owner is woken on the same
delivery contract `deployment_run_driver_notice` already implements —
a second recipient, not a second wake path. That wake resumes only a
natively wakeable surface; on a surface whose wake authority is operator
the notice stays pending until the operator types, which the merge
close-out block already told that owner. The notice fires once per
member per run on the acceptance transition. A re-read of an
already-accepted subject sends nothing.

Run-scoped QA and human-approval stages keep every member at release until all
item and shared gates pass. Settlement then closes all members atomically
through their pinned workflow's done gates; only Dash and Task prepare direct
execution evidence. A settling run supplies delivery and accepted source QA
credit before its succeeded stamp, while failed or unsettled QA still refuses.
The pipeline's advance and
`on_failure` are unchanged; a run whose other members are outstanding still
halts and still belongs to its driver.

At the member's done gate, a failed run-bound case from an earlier attempt
remains in QA history but does not block a later completion run. The later
run must satisfy its own admitted item cases and stage acceptance. A failing
case on that current run still blocks done unless its same-target replacement
passes and that stage is accepted.

Terminal settlement and code-identity checks use each requirement's newest execution; older attempts never block. Browser reviews use the capture's verdict and identity, excluding detached agent verdict rows.
A latest closed, verdict-less execution on a superseded requirement stops blocking only after its successor passes or is discharged; post-deploy successors need accepted completion-member copies.
Refusals name unsettled successors. Latest live executions and active plan executions still block; history remains unchanged.

Completion of a target-bound scoped QA execution settles its active stage
gate on the control plane. The same happens after an agent review bundle is
submitted. For `required_human`, settlement creates the authorized request
immediately; the server never supplies its answer. The frozen target digest
is checked before settlement, so old evidence cannot credit a new target.
A passed, discharged, blocked, or rejected subject requests continuation
of the same run through the existing driver notice contract. The pinned
runner still owns external stages.

Owner: `yoke_core.domain.deployment_qa_member_acceptance_notice`,
emitted from the stage-gate settlement that records acceptance.

## A human verdict reaches the agent that parked for it

A stage whose verdict policy requires a human opens a review request and
waits, and the agent that supplied the evidence parks. Resolving a
`qa_needs_review` request whose requirement is a deployment-stage subject
settles that stage gate on the server and sends a notice to the recipient
the wait itself addressed: the member's
claim holder or the project's steering seat, or the run's live driver for
a run-scoped stage. It names the run, stage, subject, outcome and the next
step — an approval releases the parked agent, a rejection hands it work, a
waiver discharges the obligation. Sent after the resolution commits and
degrading to a warning when undeliverable, because the verdict is the
durable outcome; a requirement that is not a deployment-stage subject
notifies nobody. Item-scoped decisions also notify the run driver. Owners:
`yoke_core.domain.deployment_qa_verdict_notice` and
`yoke_core.domain.deployment_qa_stage_settlement`.

The deploy driver owns run-scoped visual QA. It inspects the live target as
an agent or assigns a capable QA agent through Yoke, records evidence for
that run and stage with `yoke watch qa-plan -- --deployment-run-id RUN
--stage STAGE --project P`; settlement finishes a ready run. Add `--plan PLAN`
only when that stage names no cases. Item-scoped captures cannot credit a
run-scoped stage.

## Related

- [Release notices](release-notices.md)
