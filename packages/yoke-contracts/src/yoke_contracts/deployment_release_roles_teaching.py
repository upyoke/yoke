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

  Steering (the seat driving delivery) owns the run and nothing else. It holds
  the project deploy lock for the whole pair, pins ONE source SHA, creates the
  stage and production runs from that SHA, and starts each one. The start
  enrolls every delivery-ready item its candidate carries that no live or
  succeeded release already holds — whether the work landed since the last
  release or long before it — and applies the composition check itself, so
  membership needs no separate step:
    yoke claims coordination-claim acquire --project P --key DEPLOY:P --reason R
    yoke --env CONTROL-PLANE deployment-runs create P FLOW --environment ENV \\
      --project-repo-path /path/to/checkout --source-ref PINNED_SHA
    yoke --env CONTROL-PLANE watch deploy -- RUN-ID
    yoke claims coordination-claim release --project P --key DEPLOY:P --reason R
  `deployment-runs add-item RUN-ID PREFIX-N` is for the other case: an item
  whose code the candidate does not carry but which the run should still
  deliver. `deployment-runs validate-composition RUN-ID` composes the run now
  and reports what it enrolled or why it refused.
  An item a cancelled run left behind needs no attaching: it is held by no
  live release, so the next start takes it. `yoke steering report get` names
  any landed item no release holds, so nobody has to notice one going stale.
  Steering does not run a member's item QA and does not close a member out. A
  run-wide pass does not credit a member's item-scoped stage.

  The member owner stays parked at its release wait holding its own claim, and
  the deployment wake re-enters it. When a stage wants its evidence it credits
  that stage by naming the stage AND itself, because a stage credits only the
  requirements bound to its own name:
    yoke qa plan run --deployment-run-id RUN-ID --stage STAGE --member PREFIX-N \\
      --project P
  `--plan PLAN` goes on that line only for a stage the wake says names no
  cases; a stage already naming its own refuses it, because a plan there
  materializes a second, duplicate set of obligations beside the ones the
  stage credits.
  Then it finishes with the one agent-facing close-out:
    yoke merge item PREFIX-N --result "..." --verification "..."

  Workers never create, execute, or re-drive a deployment run; steering never
  substitutes an unscoped QA run or an internal done engine for the owner's
  close-out. Depth: `yoke qa plan run --help`, `yoke merge item --help`.
"""

__all__ = ["RELEASE_ROLE_RECIPE"]
