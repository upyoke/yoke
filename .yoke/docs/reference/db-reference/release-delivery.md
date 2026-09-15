# DB Reference — Release delivery: QA authorities, verdicts, notices

How a merged item's release is verified and announced, across the tables
[events-and-deployments.md](events-and-deployments.md) defines:
`deployment_runs`, `deployment_run_items`, `deployment_run_qa`,
`deployment_stage_receipts`, and the `qa_requirements` / `qa_runs` rows a
scoped stage settles through. Those table schemas stay there; what lives
here is the behavior that reads and writes across them.

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

## Done announces the delivery to the item's owner

Reaching done for a delivery-carrying item sends the owner one
informational notice naming the outcome, the destination it went to, the
candidate revision, and the run whose evidence backs it. Nothing reads
it: no decision, nothing to acknowledge, no gate. It goes to the same
recipient every item-addressed notice uses — the claim holder, or the
project's steering seat when the holder is gone — because the owning
agent is who holds the claim at completion.

An item with no succeeded run has no destination to name and is silent,
as is one whose run failed or was cancelled. "Once at final completion"
needs no separate guard: done happens once, the key is the item plus the
run that delivered, and a progress-delivery member does not reach done
from the run that carried it. A notice that cannot be delivered is
reported by the closeout and stays retryable — it never reverses a done
that already committed. Owners:
`yoke_core.domain.deployment_delivery_done_notice` and the registered
`done_transition.delivery_done_notice`, which the client-side engine
relays to because sending is a control-plane write.
