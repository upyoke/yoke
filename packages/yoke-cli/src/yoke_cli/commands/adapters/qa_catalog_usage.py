"""Usage strings for QA catalog flag adapters."""

from __future__ import annotations

from yoke_cli.commands.adapters.workflows_item_posture import (
    WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE,
)
from yoke_core.domain.qa_constants import (
    COMMAND_CASE_BASE_URL_ENV,
    COMMAND_CASE_DEPLOYMENT_MEMBER_ENV,
    COMMAND_CASE_DEPLOYMENT_RUN_ENV,
)


#: Read as ``yoke qa item-plan attach --help``.
ITEM_PLAN_ATTACH_EPILOG = (
    "Attaching creates a blocking case row at --transition, and there "
    "is no detach. On a workflow whose QA policy is optional item "
    "attachment, attach accepts only the plan or method already "
    "selected in workflow_posture.verification; select it first "
    f"with `{WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE}`, then attach and "
    "`yoke qa plan materialize`."
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
        "--plan-id N --transition T"
    ),
    "qa.plan.materialize": "yoke qa plan materialize --item PREFIX-N --transition T",
    "qa.plan.rematerialize": "yoke qa plan rematerialize --item PREFIX-N --transition T",
    "qa.artifact.read": (
        "yoke qa artifact read --requirement-id N --artifact-id N [--output PATH]"
    ),
}


__all__ = [
    "ITEM_PLAN_ATTACH_EPILOG",
    "PLAN_CASES_REPLACE_EPILOG",
    "USAGE_BY_FUNCTION_ID",
]
