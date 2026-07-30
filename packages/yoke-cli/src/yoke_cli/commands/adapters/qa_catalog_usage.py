"""Usage strings for QA catalog flag adapters."""

from __future__ import annotations


USAGE_BY_FUNCTION_ID = {
    "qa.method.list": "yoke qa method list --project P",
    "qa.method.get": "yoke qa method get METHOD --project P",
    "qa.project_method.register": (
        "yoke qa project-method register --project P --slug SLUG --name NAME "
        "--description TEXT --executor worktree_run "
        "--verdict-path automatic --verdict-contract TEXT "
        "--evidence-contract TEXT"
    ),
    "qa.plan.list": "yoke qa plan list --project P",
    "qa.plan.get": ("yoke qa plan get PLAN_ID --project P [--deployment-run-id RUN]"),
    "qa.activity.list": ("yoke qa activity list --project P [--deployment-run-id RUN]"),
    "qa.plan.create": (
        "yoke qa plan create SLUG --project P --target-environment ENV"
    ),
    "qa.plan_cases.replace": "yoke qa plan-cases replace --project P --plan-id N --stdin",
    "qa.project_default.set": (
        "yoke qa project-default set --project P --plan-id N "
        "--workflow W --transition T"
    ),
    "qa.item_plan.attach": (
        "yoke qa item-plan attach --item PREFIX-N --project P "
        "--plan-id N --transition T"
    ),
    "qa.plan.materialize": "yoke qa plan materialize --item PREFIX-N --transition T",
    "qa.artifact.read": "yoke qa artifact read --requirement-id N --artifact-id N",
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
