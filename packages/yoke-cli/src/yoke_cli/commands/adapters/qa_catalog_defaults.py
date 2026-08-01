"""Flag adapters for project-default QA plan attachment commands."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands.adapters.qa_catalog import _configure_attachment, _global


def qa_plan_project_default_set(args: List[str]) -> int:
    usage = (
        "yoke qa project-default set --project P --plan-id N "
        "--workflow W --transition T [--qa-phase PHASE] [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        _configure_attachment(parser)
        parser.add_argument("--workflow", required=True)

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
        "--workflow W --transition T [--json]"
    )

    def configure(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--plan-id", type=int, required=True)
        parser.add_argument("--workflow", required=True)
        parser.add_argument("--transition", required=True)

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
    "qa_plan_project_default_set",
    "qa_plan_project_default_unset",
]
