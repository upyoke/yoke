# Release QA and delivery notices

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Release notices
<!-- /yoke:breadcrumbs -->

Read how caseless stages, failed cases, settled QA results and completed deliveries are reported.

## A caseless QA stage waits rather than failing

A caseless stage lets the subject's responsible agent choose or create
evidence. Materialization refuses when nothing is pinned,
admitted or agent-selected, and that refusal is the agent's cue — so it
carries its own exception type and the dispatch treats it as a durable
wait, adding the subject to the waiting set and waking whoever can end
it (the member's claim holder at item scope, the run's live driver or
steering at run scope).

Every other materialization refusal still fails the stage. An invalid
pinned plan, an unresolvable target identity and a permission denial do
not become truer by waiting, and dressing them as patience would strand
a release behind a definition nobody is going to fix. A definition
pinning a plan that does not exist cannot even be frozen into a run —
composition freeze refuses it — so it never reaches the dispatch to be
misread, which is why only one condition needs classifying there.

## A failed case and an unrun one are different answers

A stage subject's acceptance boundary answers one of five things. Two
accept it: `passed`, and `discharged` for a subject whose every case was
waived or superseded so there was nothing left to run. Three do not:
`waiting` means something has yet to happen, `rejected` means an
authorized reviewer turned the stage's own acceptance requirement down,
and `blocked` means a scoped case holds a determinate failing verdict.

Both `blocked` and `waiting` carry `accepted=False`; neither satisfies the stage acceptance gate.

Every unaccepted answer carries `case_failures`, one record per blocking
case with a `kind` beside its sentence, because four reasons a case is
unacceptable need four different actions: `red` for a determinate failing
verdict, `unrun` for a case with no verdict, `undetermined` for a runner
that declined to decide, and `passed_without_evidence` for a case that
passed while the gate resolved no attached evidence for it. That last one
is named rather than folded in precisely because its owner sees a green
case and the gate sees an unacceptable one — re-running it produces
another passing case with the same problem, so calling it `unrun` would
send its owner to do the one thing that cannot help. A caller that needs
to tell these apart reads `case_failures` rather than matching on the
reason sentences. Owners:
`yoke_core.domain.deployment_qa_stage_outcome` for the vocabulary,
`yoke_core.domain.deployment_qa_stage_case_failures` for the
classification.

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

Only a settled result is reported: passed, discharged, or rejected. A
stage still waiting is not one, and neither is a blocked one — reporting
either would duplicate the wake that already addressed the agent, and a
blocked stage is held rather than decided. A stage that configured no notification, or
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

## Related

- [Releases](releases.md)
