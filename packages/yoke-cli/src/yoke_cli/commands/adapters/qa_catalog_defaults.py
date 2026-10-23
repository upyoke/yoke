"""Flag adapters for project-default QA plan attachment and command binding."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands.adapters.qa_catalog import _global
from yoke_cli.commands.adapters.qa_catalog_usage import (
    configure_attachment as _configure_attachment,
)


def qa_registered_command_set(args: List[str]) -> int:
    usage = (
        "yoke qa registered-command set --project P --scope quick|full|e2e|smoke "
        "--command ARGV [--environment SITE/NAME|ENV_ID | --requires-base-url] "
        "[--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--scope", required=True, metavar="quick|full|e2e|smoke",
            help="Test scope the command runs: quick, full, e2e, or smoke.",
        )
        parser.add_argument(
            "--command", required=True, metavar="ARGV",
            help="Command line that runs the tests.",
        )
        parser.add_argument(
            "--environment", dest="target_environment",
            metavar="SITE/NAME|ENV_ID",
            help="Environment the command tests, as SITE/NAME or an environment id.",
        )
        parser.add_argument(
            "--requires-base-url",
            action="store_true",
            default=None,
            help="Mark that the command needs a base URL to run.",
        )

    return _global(
        args,
        prog="yoke qa registered-command set",
        usage=usage,
        function_id="qa.registered_command.set",
        configure=configure,
        payload=lambda parsed: {
            "scope": parsed.scope,
            "command": parsed.command,
            **(
                {"target_environment": parsed.target_environment}
                if parsed.target_environment is not None
                else {}
            ),
            **(
                {"requires_base_url": True}
                if parsed.requires_base_url
                else {}
            ),
        },
    )


def qa_no_tests_attest(args: List[str]) -> int:
    usage = (
        "yoke qa no-tests attest --project P --reason TEXT "
        "[--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--reason", required=True, metavar="TEXT",
            help="Why this project has no test suite to bind.",
        )

    return _global(
        args,
        prog="yoke qa no-tests attest",
        usage=usage,
        function_id="qa.no_tests.attest",
        configure=configure,
        payload=lambda parsed: {"reason": parsed.reason},
    )


def qa_no_tests_clear(args: List[str]) -> int:
    usage = (
        "yoke qa no-tests clear --project P --reason TEXT "
        "[--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--reason", required=True, metavar="TEXT",
            help="What changed so the project now has tests.",
        )

    return _global(
        args,
        prog="yoke qa no-tests clear",
        usage=usage,
        function_id="qa.no_tests.clear",
        configure=configure,
        payload=lambda parsed: {"reason": parsed.reason},
    )


def qa_plan_project_default_set(args: List[str]) -> int:
    usage = (
        "yoke qa project-default set --project P --plan-id N "
        "--workflow W --transition T [--qa-phase PHASE] "
        "[--acknowledge-unreachable-target] [--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        _configure_attachment(parser)
        parser.add_argument(
            "--workflow", required=True, metavar="W",
            help="Workflow the default plan applies to.",
        )

    return _global(
        args,
        prog="yoke qa project-default set",
        usage=usage,
        function_id="qa.project_default.set",
        configure=configure,
        payload=lambda parsed: {
            "plan_id": parsed.plan_id,
            "workflow_id": parsed.workflow,
            "transition_id": parsed.transition,
            "qa_phase": parsed.qa_phase,
        },
    )


def qa_plan_project_default_unset(args: List[str]) -> int:
    usage = (
        "yoke qa project-default unset --project P --plan-id N "
        "--workflow W --transition T [--session-id S] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--plan-id", type=int, required=True, metavar="N",
            help="Id of the QA plan to remove as a default.",
        )
        parser.add_argument(
            "--workflow", required=True, metavar="W",
            help="Workflow the default plan applies to.",
        )
        parser.add_argument(
            "--transition", required=True, metavar="T",
            help="Workflow transition where the plan is attached.",
        )

    return _global(
        args,
        prog="yoke qa project-default unset",
        usage=usage,
        function_id="qa.project_default.unset",
        configure=configure,
        payload=lambda parsed: {
            "plan_id": parsed.plan_id,
            "workflow_id": parsed.workflow,
            "transition_id": parsed.transition,
        },
    )


__all__ = [
    "qa_no_tests_attest",
    "qa_no_tests_clear",
    "qa_plan_project_default_set",
    "qa_plan_project_default_unset",
    "qa_registered_command_set",
]
