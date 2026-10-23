"""Argument parsers for the ``yoke qa`` catalog commands."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import add_full_arg, add_json_arg, add_session_arg
from yoke_cli.commands.adapters.qa_catalog_usage import (
    ITEM_PLAN_ATTACH_EPILOG,
    configure_attachment,
)


def _split_usage(usage: str) -> tuple[str, str | None]:
    """Split a usage text into its synopsis lines and any trailing prose."""
    synopsis: list[str] = []
    prose: list[str] = []
    for line in usage.splitlines():
        if not prose and line.strip().startswith("yoke "):
            synopsis.append(line)
        else:
            prose.append(line)
    return "\n".join(synopsis), ("\n".join(prose) or None)


def build_parser(
    prog: str, usage: str, *, project_required: bool = True
) -> argparse.ArgumentParser:
    synopsis, prose = _split_usage(usage)
    parser = argparse.ArgumentParser(
        prog=prog, usage=synopsis.replace("%", "%%"), epilog=prose
    )
    parser.add_argument(
        "--project", required=project_required, metavar="P", help="Project slug or id."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def configure_method_get(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("method_id", metavar="METHOD", help="QA method id or slug.")


def configure_method_register(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slug", required=True, help="Short unique name for the method.")
    parser.add_argument("--name", required=True, help="Display name.")
    parser.add_argument(
        "--description", required=True, metavar="TEXT", help="What the method checks."
    )
    parser.add_argument(
        "--runner",
        required=True,
        choices=(
            "worktree_run",
            "browser_substrate",
        ),
        help="Where the method runs.",
    )
    parser.add_argument(
        "--verdict-path",
        required=True,
        choices=("automatic", "agent"),
        help="Whether the verdict is automatic or given by an agent.",
    )
    parser.add_argument(
        "--verdict-contract",
        required=True,
        metavar="TEXT",
        help="What a passing verdict means.",
    )
    parser.add_argument(
        "--evidence-contract",
        required=True,
        metavar="TEXT",
        help="What evidence a run must keep.",
    )
    parser.add_argument(
        "--required-capability",
        dest="required_capability_kinds",
        action="append",
        metavar="KIND",
        help="Capability kind the method needs; repeatable.",
    )
    parser.add_argument(
        "--concurrency-mode",
        choices=("parallel", "serial"),
        default="parallel",
        help="Whether runs may overlap; default: parallel.",
    )
    parser.add_argument(
        "--success-policy-params",
        default="{}",
        metavar="JSON",
        help="Success policy settings as a JSON object; default: {}.",
    )


def configure_plan_get(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "plan", nargs="?", metavar="PLAN_ID_OR_SLUG", help="Plan id or the plan's slug."
    )
    parser.add_argument(
        "--plan-id",
        metavar="PLAN_ID_OR_SLUG",
        help="Same as the positional argument; give one or the other.",
    )
    parser.add_argument(
        "--deployment-run-id",
        metavar="RUN",
        help="Include this deployment run's QA results.",
    )
    add_full_arg(parser, "each probe's source and every proof's evidence")


def configure_activity_list(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--deployment-run-id",
        metavar="RUN",
        help="Only activity for this deployment run.",
    )
    parser.add_argument(
        "--item",
        action="append",
        default=[],
        metavar="PREFIX-N",
        help="Only activity for this item; repeatable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help="Most rows to show; default: 100.",
    )


def configure_plan_create(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", metavar="SLUG", help="Slug for the new plan.")
    parser.add_argument("--name", help="Display name for the plan.")
    parser.add_argument(
        "--description", default="", metavar="TEXT", help="What the plan covers."
    )
    parser.add_argument(
        "--environment",
        required=True,
        metavar="SITE/NAME|ENV_ID",
        help=(
            "Target environment as SITE/NAME, or an environment id. A bare "
            "name resolves within the project's default site."
        ),
    )


def build_item_plan_attach_parser(usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke qa item-plan attach",
        usage=usage,
        epilog=ITEM_PLAN_ATTACH_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", required=True, metavar="PREFIX-N", help="Item id.")
    parser.add_argument(
        "--project", required=True, metavar="P", help="Project slug or id."
    )
    configure_attachment(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


__all__ = [
    "build_item_plan_attach_parser",
    "build_parser",
    "configure_activity_list",
    "configure_method_get",
    "configure_method_register",
    "configure_plan_create",
    "configure_plan_get",
]
