"""Usage strings for QA catalog flag adapters."""

from __future__ import annotations

from yoke_contracts.qa_requirement_replacement import REPLACES_METAVAR

from yoke_cli.commands.adapters.qa_item_plan_retract import (
    QA_ITEM_PLAN_RETRACT_USAGE,
)
from yoke_cli.commands.adapters.qa_catalog_help import (
    ITEM_PLAN_ATTACH_EPILOG,
    PLAN_CASES_REPLACE_EPILOG,
    PLAN_MATERIALIZE_EPILOG,
    PLAN_REMATERIALIZE_EPILOG,
)


PLAN_CASES_SYNC_USAGE = (
    "yoke qa plan-cases sync --project P --plan-id N (--cases-file PATH | "
    "--stdin) [--session-id S] [--json]\n"
    "       yoke qa plan-cases sync --project P --plan-id N (--cases-file PATH | "
    "--stdin) --source-revision FULL_SHA [--session-id S] [--json]\n"
    "Without --source-revision, the input must be the exporter's document. "
    "Write a manual case array with yoke qa plan-cases replace."
)

USAGE_BY_FUNCTION_ID = {
    "qa.method.list": ("yoke qa method list [--project P] [--session-id S] [--json]"),
    "qa.method.get": (
        "yoke qa method get METHOD [--project P] [--session-id S] [--json]"
    ),
    "qa.project_method.register": (
        "yoke qa project-method register --project P --slug SLUG --name "
        "NAME --description TEXT --runner worktree_run --verdict-path "
        "automatic --verdict-contract TEXT --evidence-contract TEXT "
        "[--required-capability KIND ...] [--session-id S] [--json] "
        "[--concurrency-mode {parallel,serial}] "
        "[--success-policy-params JSON]"
    ),
    "qa.plan.list": (
        "yoke qa plan list --project P [--limit N] [--offset N] "
        "[--include-retired] [--full] [--session-id S] [--json]"
    ),
    "qa.plan.get": (
        "yoke qa plan get (PLAN_ID_OR_SLUG | --plan-id PLAN_ID_OR_SLUG) --project P "
        "[--deployment-run-id RUN] [--full] [--session-id S] [--json]"
    ),
    "qa.activity.list": (
        "yoke qa activity list --project P [--deployment-run-id RUN] "
        "[--item PREFIX-N ...] [--limit N] [--full] [--session-id S] [--json]"
    ),
    "qa.plan.create": (
        "yoke qa plan create SLUG --project P "
        "--environment ENV [--session-id S] [--json] "
        "[--name NAME] [--description TEXT]"
    ),
    "qa.plan_cases.replace": (
        "yoke qa plan-cases replace --project P --plan-id N "
        "(--stdin | --cases-file PATH) [--source-revision FULL_SHA] "
        "[--session-id S] [--json]"
    ),
    "qa.plan_cases.sync": PLAN_CASES_SYNC_USAGE,
    "qa.registered_command.set": (
        "yoke qa registered-command set --project P --scope "
        "quick|full|e2e|smoke --command ARGV [--environment "
        "SITE/NAME|ENV_ID | --requires-base-url] [--session-id S] "
        "[--json]"
    ),
    "qa.no_tests.attest": (
        'yoke qa no-tests attest --project P --reason "why this project '
        'has no suite to bind" [--session-id S] [--json]'
    ),
    "qa.no_tests.clear": (
        "yoke qa no-tests clear --project P --reason "
        '"what changed" [--session-id S] [--json]'
    ),
    "qa.project_default.set": (
        "yoke qa project-default set --project P --plan-id N --workflow "
        "W --transition T [--session-id S] [--json] [--qa-phase PHASE] "
        "[--acknowledge-unreachable-target]"
    ),
    "qa.project_default.unset": (
        "yoke qa project-default unset --project P --plan-id N "
        "--workflow W --transition T [--session-id S] [--json]"
    ),
    "qa.item_plan.attach": (
        "yoke qa item-plan attach --item PREFIX-N --project P --plan-id "
        "N --transition T [--qa-phase post_deploy] "
        "[--acknowledge-unreachable-target] [--session-id S] [--json]"
    ),
    "qa.item_plan.retract": QA_ITEM_PLAN_RETRACT_USAGE,
    "qa.plan.materialize": (
        "yoke qa plan materialize "
        "(--item PREFIX-N (--transition T | --stage STAGE [--plan PLAN]) "
        "[--project P] | --deployment-run-id RUN --project P "
        "(--plan PLAN [--stage STAGE] | --stage STAGE)) "
        f"[--replaces {REPLACES_METAVAR} ...] "
        "[--replaces-requirement REQUIREMENT_ID ...] [--session-id S] [--json]"
    ),
    "qa.plan.rematerialize": (
        "yoke qa plan rematerialize "
        "(--item PREFIX-N (--transition T | --stage STAGE [--plan PLAN]) | "
        "--deployment-run-id RUN --stage STAGE [--plan PLAN]) "
        "[--project P] [--session-id S] [--json]"
    ),
    "qa.artifact.read": (
        "yoke qa artifact read --requirement-id N --artifact-id N "
        "[--output PATH] [--region x,y,w,h] [--scale N] [--session-id "
        "S] [--json]"
    ),
}


__all__ = [
    "ITEM_PLAN_ATTACH_EPILOG",
    "PLAN_MATERIALIZE_EPILOG",
    "PLAN_CASES_REPLACE_EPILOG",
    "PLAN_REMATERIALIZE_EPILOG",
    "USAGE_BY_FUNCTION_ID",
]


def configure_attachment(parser) -> None:
    """Declare the attachment fields shared with its help contract."""
    parser.add_argument(
        "--plan-id",
        required=True,
        type=int,
        metavar="N",
        help="Id of the QA plan to attach.",
    )
    parser.add_argument(
        "--transition",
        required=True,
        metavar="T",
        help="Workflow transition the plan must pass before.",
    )
    parser.add_argument(
        "--qa-phase",
        default="verification",
        metavar="PHASE",
        help=("verification, post_deploy or manual_acceptance; default: verification."),
    )
    parser.add_argument(
        "--acknowledge-unreachable-target",
        action="store_true",
        help="Attach even though the plan's target looks unreachable here.",
    )
