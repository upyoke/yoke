"""CLI teaching for who does what during an item-bound batch release.

A deployment run that carries members has three roles acting on it, and each
one reaches for a different command. The run driver and the member owners are
different sessions, so neither can discover the other's command by reading its
own skill: this is the surface both of them open. Keep wording project-generic.

The itemless environment-release path is a sibling concern and lives in
:mod:`yoke_contracts.deployment_itemless_teaching`.
"""

from __future__ import annotations

RELEASE_ROLE_RECIPE = """\
Item-bound batch release — who runs what:

  Steering (the seat driving delivery) owns the run and nothing else. It pins
  ONE source SHA, creates the stage and production runs from that SHA, and
  starts each one. No claim is taken: a run occupies the servers it deploys to
  until its QA settles or it is terminal, so a run aimed at an occupied server
  refuses naming the holder, and a run's live driver is the only session its
  execution answers to. Creating a run on the flow and target of a run that
  waits only on item QA takes that run over when the new candidate contains
  its candidate: waiting members move to the new run (every unclosed member
  when the flow has run-level QA or approval, which cancels the older run as
  superseded). Open walks carry intact to the successor before the older run
  ends; never hold a release for an open walk. `deployment-runs create --help`
  has the rules. On a flow
  that waits for CI that SHA needs its own CI run: create the CI-gated run
  without --source-ref to bind one, then pin its release_lineage. The start
  enrolls every delivery-ready item its candidate carries that no live or
  succeeded release already holds — whether the work landed since the last
  release or long before it — and applies the composition check itself, so
  membership needs no separate step:
    yoke --env CONTROL-PLANE deployment-runs create P FLOW --environment ENV \\
      --project-repo-path /path/to/checkout --source-ref PINNED_SHA \\
      --idempotency-key ENV-PINNED_SHA-1
    yoke --env CONTROL-PLANE watch deploy -- RUN-ID
  `deployment-runs add-item RUN-ID PREFIX-N` is for the other case: an item
  whose code the candidate does not carry but which the run should still
  deliver. `deployment-runs validate-composition RUN-ID` composes the run now
  and reports what it enrolled or why it refused.
  An item a cancelled run left behind needs no attaching: it is held by no
  live release, so the next start takes it. `yoke steering report get` names
  any landed item no release holds, so nobody has to notice one going stale.
  For red member QA, `yoke deployment-runs remove-item RUN ITEM --reason R` lets an independent run finish while the member waits for its next release; see `remove-item --help`. Failed independent item QA automatically releases a member whose recorded merge is definitely outside its project's frozen lineage, using the same audited removal as settlement; unknown containment holds and reports recovery. Settlement also releases replaced candidates, and resume and settlement both release a member reopened for rework after the run froze whose current candidate is outside the frozen lineage, settled QA included; a contained one stays and unknown containment refuses by name.
  Steering does not run a member's item QA and does not close a member out. A
  run-wide pass does not credit a member's item-scoped stage. Completed scoped
  execution settles its gate on the server and opens required human review;
  a resolved decision requests continuation of the same run. Re-enter the
  pinned runner on that run after a continuation notice.

  The deploy driver owns run-scoped QA. Read the stage's plan partitions:
    yoke qa plan partitions --deployment-run-id RUN-ID --stage STAGE --plan PLAN --project P
  The driver runs command-only partitions. For each free walk, use the
  itemless launch recipe in .yoke/docs/verification/walking.md#launch-a-walker
  with your own level explicitly in --level.

  The member owner stays parked at its release wait holding its own claim, and
  on a natively wakeable surface the deployment wake re-enters it for its QA
  stage, when its own item-scoped QA is accepted, and when delivery clears. A
  surface whose wake authority is operator (a desktop app) is never resumed by
  Yoke: its operator or a steering seat re-enters that owner. When a stage wants its evidence it credits
  that stage by naming the stage AND itself, because a stage credits only the
  requirements bound to its own name:
    yoke qa plan partitions --item PREFIX-N --stage STAGE --deployment-run-id RUN --project P
  Run command-only partitions and launch each free walk using the guide above.
  The holder keeps the claim, takes requested_level from the item launch preview
  and passes it explicitly to launch create. Add --plan PLAN only when the
  stage notice asks for a plan.
  Then it finishes with the one agent-facing close-out:
    yoke merge item PREFIX-N --result "..." --verification "..."

  Workers never create, execute, or re-drive a deployment run; steering never
  substitutes an unscoped QA run or an internal done engine for the owner's
  close-out. Depth: `yoke qa plan partitions --help`, `yoke merge item --help`.
"""

__all__ = ["RELEASE_ROLE_RECIPE"]
