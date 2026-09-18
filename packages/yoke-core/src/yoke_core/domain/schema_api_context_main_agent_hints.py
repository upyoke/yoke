"""Compact hints appended to the ``main_agent`` packet only.

The topic packets carry what every role holding that topic needs. These two
facts belong to the top-level session alone, so they ride here rather than
widening a shared topic: a main session inspects deployment-run rows and acts
at release time, while the subagent roles do neither.

Both are compact-body text and count against the role's packet budget; keep
them one rendered line each.
"""

from __future__ import annotations

#: Column shapes a raw deployment-run diagnostic SELECT gets wrong, named so a
#: main session does not confabulate `target_env` or `deployment_runs.item_id`.
DEPLOYMENT_RUN_QUERY_HINT = (
    "**Deployment-run raw-query hint:** "
    "`deployment_flows.target_environment_id` references "
    "`environments.id` (JOIN environments for the display name; "
    "`target_tier` is persistent/ephemeral/NULL — there is no "
    "`target_env` column); `deployment_runs.status` and "
    "`deployment_runs.current_stage` record progress. There is no "
    "`deployment_runs.item_id`; join through `deployment_run_items` "
    "for item-bound runs. `deployment_runs.carried_work` is the "
    "inert JSON record of what a succeeded run shipped: resolved "
    "items plus unresolved bare commits."
)

#: Which release-time command belongs to the seat driving a run and which to
#: the member owner parked at its release wait. The two act on the same run
#: from different sessions, so neither learns the other's part from its own
#: skill; substituting one for the other is what leaves a stage uncredited or
#: an item unclosed.
RELEASE_ROLE_HINT = (
    "**Release-time commands by role:** the seat driving delivery "
    "holds `DEPLOY:<project>` for the whole pair and owns "
    "`deployment-runs create` / `add-item` / "
    "`validate-composition` / `watch deploy` -- it never runs a "
    "member's item QA and never closes a member out. The member "
    "owner stays parked at its release wait holding its own claim; "
    "when the deployment wake asks for its stage it credits that "
    "stage with `yoke qa plan run --deployment-run-id RUN --stage "
    "STAGE --member PREFIX-N --plan PLAN --project P` (a stage "
    "credits only requirements bound to its own name, so the "
    "run-wide form is refused), then finishes with the one "
    "agent-facing close-out `yoke merge item PREFIX-N --result ... "
    "--verification ...`. There is no internal done engine to "
    "substitute. Depth: those commands' `--help`."
)

MAIN_AGENT_HINTS = (DEPLOYMENT_RUN_QUERY_HINT, RELEASE_ROLE_HINT)

__all__ = [
    "DEPLOYMENT_RUN_QUERY_HINT",
    "MAIN_AGENT_HINTS",
    "RELEASE_ROLE_HINT",
]
