"""Main-session delivery depth in explicit project-topic reads."""

from __future__ import annotations

#: Column shapes a raw deployment-run diagnostic SELECT gets wrong, named so a
#: main session does not confabulate `target_env` or `deployment_runs.item_id`.
DEPLOYMENT_RUN_QUERY_HINT = (
    "**Deployment-run raw-query hint:** "
    "`deployment_flows.target_environment_id` references "
    "`environments.id` (JOIN environments for the display name); "
    "`target_tier` is persistent/ephemeral/NULL. `deployment_runs.status` and "
    "`deployment_runs.current_stage` record progress. Join through `deployment_run_items` "
    "for item-bound runs. `deployment_runs.carried_work` records "
    "resolved items and unresolved bare commits; a warning that "
    "changes what the run can attest is `deployment_runs.get` "
    "`attestation_warnings` (reason, cost, recovery), not a parse "
    "of that JSON column."
)

#: Which release-time command belongs to the seat driving a run and which to
#: the member owner parked at its release wait. The two act on the same run
#: from different sessions, so neither learns the other's part from its own
#: skill; substituting one for the other is what leaves a stage uncredited or
#: an item unclosed.
RELEASE_ROLE_HINT = (
    "**Release-time commands by role:** the seat driving delivery "
    "holds `DEPLOY:<project>` for the whole pair, pins one source "
    "SHA, and owns `deployment-runs create` plus `watch deploy` for "
    "each run -- the start enrolls every delivery-ready item the "
    "candidate carries that no live or succeeded release already "
    "holds, and applies the composition check itself. `add-item` is "
    "for an item whose code the candidate does not carry but which "
    "the run should still deliver; `validate-composition` composes "
    "the run now and reports what enrolled or why it refused. That "
    "seat never "
    "runs a member's item QA and never closes a member out. The member "
    "owner stays parked at its release wait holding its own claim; "
    "when the deployment wake asks for its stage (an operator-woken "
    "desktop owner is re-entered by its operator or a steering seat "
    "instead, and an item owing nothing closes with no re-entry) it "
    "credits that "
    "stage with `yoke qa plan run --deployment-run-id RUN --stage "
    "STAGE --member PREFIX-N --project P` (a stage "
    "credits only requirements bound to its own name, so the "
    "run-wide form is refused), adding `--plan PLAN` only for a "
    "stage the wake says names no cases -- one that already names "
    "its own refuses it. A delivery wake names the one "
    "agent-facing close-out `yoke merge item PREFIX-N --result ... "
    "--verification ...` only when automatic close-out could not "
    "finish. There is no internal done engine to "
    "substitute. Depth: those commands' `--help`."
)

MAIN_AGENT_HINTS = (DEPLOYMENT_RUN_QUERY_HINT, RELEASE_ROLE_HINT)

__all__ = [
    "DEPLOYMENT_RUN_QUERY_HINT",
    "MAIN_AGENT_HINTS",
    "RELEASE_ROLE_HINT",
]
