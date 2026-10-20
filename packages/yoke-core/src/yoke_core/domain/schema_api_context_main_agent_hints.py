"""Main-session delivery depth in explicit project-topic reads."""

from __future__ import annotations

#: Column shapes a raw deployment-run SELECT gets wrong.
DEPLOYMENT_RUN_QUERY_HINT = (
    "**Deployment-run raw-query hint:** "
    "`deployment_flows.target_environment_id` references `environments.id`; "
    "`target_tier` is persistent/ephemeral/NULL. `deployment_runs.status` and "
    "`deployment_runs.current_stage` record progress. Join through "
    "`deployment_run_items` for item-bound runs. Read warnings from "
    "`deployment_runs.get` `attestation_warnings`, not by parsing "
    "`deployment_runs.carried_work`."
)

#: The delivery seat and a parked member owner act on the same run from
#: different sessions, so neither learns the other's part from its own skill.
RELEASE_ROLE_HINT = (
    "**Release-time commands by role:** the delivery seat pins one source SHA "
    "and runs `deployment-runs create` and `watch deploy` for each run, with no "
    "claim; it never runs a member's item QA or closes a member out. A member "
    "owner stays parked at its release wait, holding its claim. When the "
    "deployment wake asks for its stage, it runs `yoke qa plan run "
    "--deployment-run-id RUN --stage STAGE --member PREFIX-N --project P` "
    "(add `--plan PLAN` only when the wake says the stage names no cases). A "
    "stage held by another session returns waiting: keep the claim and park. "
    "Run `yoke merge item PREFIX-N --result ... --verification ...` only when "
    "a delivery wake names it. Depth: each command's `--help`."
)

SETUP_FACTS_HINT = (
    "**Setup facts:** `yoke onboard checklist get --json` serves "
    "`run.next_action` and `run.setup_readiness`. Configured, verified, "
    "deferred, not-needed and unknown are states; blocked names a required "
    "repair. Follow next_action instead of deriving a step."
)

MAIN_AGENT_HINTS = (DEPLOYMENT_RUN_QUERY_HINT, RELEASE_ROLE_HINT, SETUP_FACTS_HINT)

__all__ = [
    "DEPLOYMENT_RUN_QUERY_HINT",
    "MAIN_AGENT_HINTS",
    "RELEASE_ROLE_HINT",
]
