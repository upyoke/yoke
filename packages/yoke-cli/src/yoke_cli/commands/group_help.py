"""Namespace-prefix help for registered ``yoke`` command groups."""

from __future__ import annotations

from difflib import get_close_matches
from typing import List, Optional, Sequence

from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.help_labels import labeled_cli_form
from yoke_cli.commands.registry import (
    SPACE_EXPANDED_ROUTE_REGISTRY,
    SUBCOMMAND_ALIAS_REGISTRY,
    SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS, TOOL_SHAPED_USAGE
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER


GROUP_ROUTES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {
    ("deployments",): (("deployment-flows",), ("deployment-runs",)),
    ("worktrees",): (("item-worktrees",),),
    ("source",): (("source-authority",),),
    ("qa", "review"): (("qa", "plan"),),
    ("github", "actions", "get"): (("github-actions",),),
    ("github", "actions", "wait"): (("github-actions",),),
}

GUIDANCE_ROUTES: dict[tuple[str, ...], str] = {
    ("simulate",): (
        "Simulation is a harness skill, not a terminal adapter. "
        "Run `/yoke simulate PREFIX-N` or `/yoke simulate --system`."
    ),
}


def emit_group_help_if_available(argv: Sequence[str]) -> Optional[int]:
    help_requested = bool(argv) and argv[-1] in ("-h", "--help", "help")
    prefix = tuple(argv[:-1] if help_requested else argv)
    if not prefix:
        return None

    if prefix in GUIDANCE_ROUTES:
        print(GUIDANCE_ROUTES[prefix])
        return 0

    routed_prefixes = GROUP_ROUTES.get(prefix, (prefix,))

    rows: List[tuple[str, str, str]] = []
    registry_rows = {
        **SUBCOMMAND_REGISTRY,
        **SUBCOMMAND_ALIAS_REGISTRY,
    }
    for cli_tokens, (function_id, _adapter) in sorted(registry_rows.items()):
        if not any(
            len(cli_tokens) > len(route) and cli_tokens[:len(route)] == route
            for route in routed_prefixes
        ):
            continue
        cli_form = "yoke " + " ".join(cli_tokens)
        rows.append((cli_form, function_id, ADAPTER_USAGE.get(function_id, "")))

    tool_rows: List[tuple[str, str]] = []
    for cli_form, usage in sorted(TOOL_SHAPED_USAGE.items()):
        tokens = tuple(cli_form.split()[1:])
        if not any(
            len(tokens) > len(route) and tokens[:len(route)] == route
            for route in routed_prefixes
        ):
            continue
        tool_rows.append((cli_form, usage))

    if not rows and not tool_rows:
        return None

    group = " ".join(prefix)
    print(f"yoke {group} - subcommand group.")
    print()
    print("Usage:")
    print(f"  yoke {group} <subcommand> [args...]")
    print()
    print("Available subcommands:")
    for cli_form, function_id, usage in rows:
        print(f"  {labeled_cli_form(cli_form)}")
        print(f"    -> {function_id}")
        if usage:
            print(f"    {usage}")
    for cli_form, usage in tool_rows:
        print(f"  {labeled_cli_form(cli_form)}")
        print("    -> client-local helper (no function id)")
        if usage:
            print(f"    {usage}")
    print()
    print(FIELD_NOTE_FOOTER)
    return 0


def can_route_group(argv: Sequence[str]) -> bool:
    """Return whether the CLI routes this exact spelling to useful guidance."""
    prefix = tuple(argv)
    if not prefix:
        return False
    if prefix in GROUP_ROUTES or prefix in GUIDANCE_ROUTES:
        return True
    all_tokens = (
        tuple(SUBCOMMAND_REGISTRY)
        + tuple(SUBCOMMAND_ALIAS_REGISTRY)
        + tuple(SPACE_EXPANDED_ROUTE_REGISTRY)
        + tuple(TOOL_SHAPED_SUBCOMMANDS)
    )
    return any(
        len(tokens) > len(prefix) and tokens[:len(prefix)] == prefix
        for tokens in all_tokens
    )


def nearest_subcommand_hint(argv: Sequence[str]) -> str | None:
    """Suggest the nearest real member when an existing group is mistyped."""
    if not argv:
        return None
    all_tokens = (
        tuple(SUBCOMMAND_REGISTRY)
        + tuple(SUBCOMMAND_ALIAS_REGISTRY)
        + tuple(SPACE_EXPANDED_ROUTE_REGISTRY)
        + tuple(TOOL_SHAPED_SUBCOMMANDS)
    )
    group = argv[0]
    candidates = [
        " ".join(tokens)
        for tokens in all_tokens
        if tokens and (tokens[0] == group or tokens[0].split("-")[0] == group)
    ]
    if not candidates:
        return None
    requested = " ".join(argv)
    matches = get_close_matches(requested, candidates, n=1, cutoff=0.35)
    if not matches:
        return None
    return f"Did you mean `yoke {matches[0]}`?"


__all__ = [
    "GROUP_ROUTES",
    "GUIDANCE_ROUTES",
    "can_route_group",
    "emit_group_help_if_available",
    "nearest_subcommand_hint",
]
