"""Usage strings for QA catalog flag adapters."""

from __future__ import annotations

from yoke_cli.commands.adapters.qa_item_plan_retract import (
    QA_ITEM_PLAN_RETRACT_USAGE,
)
from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE,
)
from yoke_contracts.qa_case_environment import (
    COMMAND_CASE_BASE_URL_ENV,
    COMMAND_CASE_DEPLOYMENT_MEMBER_ENV,
    COMMAND_CASE_DEPLOYMENT_RUN_ENV,
)


#: Read as ``yoke qa item-plan attach --help``.
ITEM_PLAN_ATTACH_EPILOG = (
    "Attaching creates a blocking case row at --transition. A plan bound "
    "to the item's completion-flow environment cannot attach at a "
    "transition that precedes delivery there: the revision probe resolves "
    "from that target, so the requirement can never pass and the item "
    "cannot enter release. A catalog plan bound to a different environment "
    "still attaches. Attach the delivery-target plan at the item's "
    "post-deploy transition instead (`--qa-phase post_deploy`). A caller "
    "who knows the target is already reachable may pass "
    "`--acknowledge-unreachable-target`. A mis-specified post-deploy "
    "attachment is withdrawn with `yoke qa item-plan retract` — the row "
    "stays as retracted history; there is no detach. On a workflow whose "
    "QA policy is optional item attachment, attach accepts only the plan "
    "or method already selected in workflow_posture.verification; select "
    f"it first with `{WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE}`, then attach "
    "and `yoke qa plan materialize`."
)

#: Read as ``yoke qa plan-cases replace --help``. What an author has to know
#: to write the case array, and what their command is handed when it runs.
PLAN_CASES_REPLACE_EPILOG = f"""\
The case array
--------------
Each case is a JSON object: case_key, method_id, instructions,
expected_outcome, and the method's own method_config. `position` is optional
-- omit it and each case takes its place in the array, which is the order you
wrote them in. Supply it only to state an order the array does not.

What a Command case's shell is handed
-------------------------------------
{COMMAND_CASE_BASE_URL_ENV}: the target the case runs against.
{COMMAND_CASE_DEPLOYMENT_RUN_ENV}: the deployment run this case answers for.
{COMMAND_CASE_DEPLOYMENT_MEMBER_ENV}: the member that run is proving, as PREFIX-N.

The last two are set only for a case bound to a deployment run and member,
and they are how such a case names its own subject. A command that writes a
run id or a member ref as a literal is correct for exactly one run and then
reports on the wrong one; read these instead, and the same plan keeps working
on every release.

What this does NOT reach
------------------------
Replacing cases writes the plan. Rows already materialized from it keep the
body they were materialized with, so the result reports
requirements_behind_plan: every such row, the fields that moved, and the
`yoke qa plan rematerialize` invocation that reaches that exact row. An empty
list means nothing is behind the plan. Read it — a correction that stops at
the plan is a correction the case that actually runs never received.
"""

#: Read as ``yoke qa plan rematerialize --help``. The one route from a
#: corrected plan to the rows that run it, and where it stops.
PLAN_REMATERIALIZE_EPILOG = """Bringing live rows to the plan's current text
---------------------------------------------
This is the supported way to correct a materialized case. It refreshes
matching rows in place, retains their QA run history, creates cases the plan
has gained, and waives cases it has lost. It reaches every executable column,
instructions and expected_outcome included -- which `yoke qa requirement
update` cannot write at all -- because it rewrites the derivation whole rather
than one allowlisted field. It also carries that body onto every admitted
deployment-stage copy frozen from a refreshed row that can still be reached,
reported as corrected_admitted_copy_ids -- otherwise the copy would keep the
old body and its stage would refuse the case as superseded.

A deployment subject refreshes only cases that have not recorded a
determinate verdict; one that has already answered is an acceptance record,
so the call refuses and names it for `yoke qa requirement supersede` instead.
The subject keeps the deployment target its stage receipt pinned --
rematerializing never re-points a frozen run at the plan's current
environment. A declaration correction of the same environment identity, or a
snapshot whose endpoints already match the resolved environment while
its identity labels are stale, is not rematerialize's job:
`yoke qa requirement rebind-target` points the stored digest at the
live facts and keeps the recorded verdict. A live item requirement
cannot be superseded.

Where it refuses instead
------------------------
It will not move a row something else has already frozen a copy of, and it
decides that before writing anything, so a refused refresh leaves every row
exactly as it was.

plan_execution_in_flight: a live QA plan execution is walking a roster built
from these rows. The refusal names the execution and the full
`yoke qa plan abort` invocation that reopens the refresh.

admitted_copy_in_flight: an admitted deployment-stage copy of a row is on a
run that is still executing and cannot be corrected. The refusal names the
copy, its run, and the remedy available for that copy.

Reading drift without two bodies
--------------------------------
`yoke qa requirement list` reports plan_currency per materialized row --
current, stale with plan_diverging_fields, orphaned, or unreadable.
"""

USAGE_BY_FUNCTION_ID = {
    "qa.method.list": "yoke qa method list --project P",
    "qa.method.get": "yoke qa method get METHOD --project P",
    "qa.project_method.register": (
        "yoke qa project-method register --project P --slug SLUG --name NAME "
        "--description TEXT --runner worktree_run "
        "--verdict-path automatic --verdict-contract TEXT "
        "--evidence-contract TEXT [--required-capability KIND ...]"
    ),
    "qa.plan.list": "yoke qa plan list --project P",
    "qa.plan.get": (
        "yoke qa plan get PLAN_ID --project P [--deployment-run-id RUN] "
        "[--full] [--json]"
    ),
    "qa.activity.list": (
        "yoke qa activity list --project P [--deployment-run-id RUN] "
        "[--item-id N ...] [--limit N] [--json]"
    ),
    "qa.plan.create": ("yoke qa plan create SLUG --project P --environment ENV"),
    "qa.plan_cases.replace": "yoke qa plan-cases replace --project P --plan-id N --stdin",
    "qa.registered_command.set": (
        "yoke qa registered-command set --project P "
        "--scope quick|full|e2e|smoke --command ARGV "
        "[--environment SITE/NAME|ENV_ID | --requires-base-url]"
    ),
    "qa.no_tests.attest": (
        "yoke qa no-tests attest --project P "
        '--reason "why this project has no suite to bind"'
    ),
    "qa.no_tests.clear": ('yoke qa no-tests clear --project P --reason "what changed"'),
    "qa.project_default.set": (
        "yoke qa project-default set --project P --plan-id N "
        "--workflow W --transition T"
    ),
    "qa.project_default.unset": (
        "yoke qa project-default unset --project P --plan-id N "
        "--workflow W --transition T"
    ),
    "qa.item_plan.attach": (
        "yoke qa item-plan attach --item PREFIX-N --project P "
        "--plan-id N --transition T [--acknowledge-unreachable-target]"
    ),
    "qa.item_plan.retract": QA_ITEM_PLAN_RETRACT_USAGE,
    "qa.plan.materialize": "yoke qa plan materialize --item PREFIX-N --transition T",
    "qa.plan.rematerialize": "yoke qa plan rematerialize --item PREFIX-N --transition T",
    "qa.artifact.read": (
        "yoke qa artifact read --requirement-id N --artifact-id N [--output PATH]"
    ),
}


__all__ = [
    "ITEM_PLAN_ATTACH_EPILOG",
    "PLAN_CASES_REPLACE_EPILOG",
    "PLAN_REMATERIALIZE_EPILOG",
    "USAGE_BY_FUNCTION_ID",
]
