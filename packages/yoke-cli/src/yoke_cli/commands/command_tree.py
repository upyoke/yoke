"""Progressive command discovery from the CLI's live route owners."""

from __future__ import annotations

from yoke_cli.commands.registry import (
    SUBCOMMAND_REGISTRY,
    SUBCOMMAND_ALIAS_REGISTRY,
    SPACE_EXPANDED_ROUTE_REGISTRY,
    SPACED_GROUP_ROUTE_REGISTRY,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS
from yoke_cli.commands.help_labels import labeled_cli_form


def command_routes() -> dict:
    """All supported spellings, including convenience and local commands."""
    return {
        **SPACE_EXPANDED_ROUTE_REGISTRY,
        **SUBCOMMAND_ALIAS_REGISTRY,
        **SUBCOMMAND_REGISTRY,
        **{
            route: (None, adapter) for route, adapter in TOOL_SHAPED_SUBCOMMANDS.items()
        },
    }


def listed_routes() -> set[tuple[str, ...]]:
    """Command spellings help lists; a split leaf resolves but is never listed."""
    return {
        *SUBCOMMAND_REGISTRY,
        *SUBCOMMAND_ALIAS_REGISTRY,
        *SPACED_GROUP_ROUTE_REGISTRY,
        *TOOL_SHAPED_SUBCOMMANDS,
    }


def discovery_routes() -> set[tuple[str, ...]]:
    from yoke_cli.commands.group_help import GROUP_ROUTES, GUIDANCE_ROUTES

    return listed_routes() | set(GROUP_ROUTES) | set(GUIDANCE_ROUTES)


def _children(prefix: tuple[str, ...], routes) -> set[tuple[str, ...]]:
    return {
        route[: len(prefix) + 1]
        for route in routes
        if len(route) > len(prefix) and route[: len(prefix)] == prefix
    }


def immediate_children(prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Children of ``prefix``; executable routes remain visible beside siblings."""
    routes = discovery_routes()
    children = _children(prefix, routes)
    spaced_only = children - _children(prefix, routes - set(SPACED_GROUP_ROUTE_REGISTRY))
    names = {child[-1] for child in children}
    return sorted(
        child
        for child in children
        if child in routes
        or child not in spaced_only
        or not any(name.startswith(child[-1] + "-") for name in names)
    )


def child_lines(prefix: tuple[str, ...]) -> list[str]:
    """One line per child: its name, then its one-line summary."""
    from yoke_cli.commands.command_summaries import summary_for

    rows = [
        (labeled_cli_form("yoke " + " ".join(child)), summary_for(child))
        for child in immediate_children(prefix)
    ]
    width = max((len(name) for name, _ in rows), default=0)
    return [f"  {name:<{width}}  {summary}".rstrip() for name, summary in rows]


def render_root_help() -> str:
    return "\n".join(
        [
            "yoke — plan, build, verify and deliver software with people and agents.",
            "",
            "Usage: yoke [--env NAME] <command> [arguments]",
            "",
            "Start: yoke setup",
            "Inspect: yoke status",
            "Help: yoke <category> --help; then yoke <command> --help",
            "Each command's help owns its recipe, options and prerequisites.",
            "",
            "Categories and actions (open --help for each):",
            *child_lines(()),
            "",
            "Global options: --env NAME selects a connection; --version prints the release.",
            "Structured replies: add --json. Complete read detail: add --full when offered.",
            "Installed project: /yoke help; reference: .yoke/docs/index.md.",
            "Without a project: https://upyoke.com/docs; command help works from any directory.",
        ]
    )
