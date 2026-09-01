"""Namespace-prefix help for registered ``yoke`` command groups."""

from __future__ import annotations

import sys
from difflib import get_close_matches
from typing import List, Optional, Sequence, TextIO

from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.help_labels import labeled_cli_form
from yoke_cli.commands.registry import (
    SPACE_EXPANDED_ROUTE_REGISTRY,
    SUBCOMMAND_ALIAS_REGISTRY,
    SUBCOMMAND_REGISTRY,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS, TOOL_SHAPED_USAGE
from yoke_contracts.connection_authority_teaching import DB_GROUP_TEACHING
from yoke_contracts.deployment_itemless_teaching import (
    ITEMLESS_RELEASE_RECIPE,
)
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER

GROUP_ROUTES: dict[tuple[str, ...], tuple[tuple[str, ...], ...]] = {
    ("deployments",): (("deployment-flows",), ("deployment-runs",)),
    ("worktrees",): (("item-worktrees",),),
    ("source",): (("source-authority",),),
    ("environment",): (
        ("projects", "environment"),
        ("projects", "environment-settings"),
    ),
    ("environments",): (
        ("projects", "environment"),
        ("projects", "environment-settings"),
    ),
    ("qa", "review"): (("qa", "plan"),),
    ("github", "actions", "get"): (("github", "actions"),),
    ("github", "actions", "wait"): (("github", "actions"),),
}

GUIDANCE_ROUTES: dict[tuple[str, ...], str] = {
    ("simulate",): (
        "Simulation is a harness skill, not a terminal adapter. "
        "Run `/yoke simulate PREFIX-N` or `/yoke simulate --system`."
    ),
}

# Printed after the subcommand list when operators open group help. Each
# entry answers a question the listing itself cannot: the surface an
# operator reaches for under this prefix lives somewhere else, or does not
# exist at all and the capability is reached another way.
GROUP_TEACHING: dict[tuple[str, ...], str] = {
    ("db",): DB_GROUP_TEACHING,
    ("deployment-runs",): ITEMLESS_RELEASE_RECIPE,
    ("env",): (
        "Retirement is a `connection` command: `yoke connection remove ENV` "
        "deletes the entry and its Yoke-owned credential, taking "
        "`--activate ENV` when the entry being removed is the active "
        "authority. There is no `env remove`, and no entry ever needs "
        "hand-editing out of ~/.yoke/config.json."
    ),
    ("connection",): (
        "Discovery: `yoke env list` prints every configured connection "
        "(name, active, transport, prod flag, api url). There is no "
        "`connection list`."
    ),
    ("project",): (
        "Reading the machine's project mappings is a `projects` (plural) "
        "surface: `yoke projects list` for every registered project, "
        "`yoke projects checkout-context` for the one owning this checkout."
    ),
    ("sessions",): (
        "Liveness: there is no standalone heartbeat command. "
        "`yoke sessions touch`, `yoke sessions offer`, and "
        "`yoke sessions checkpoint` each refresh the session's heartbeat."
    ),
}


def _extends(tokens: tuple[str, ...], route: tuple[str, ...]) -> bool:
    return len(tokens) > len(route) and tokens[:len(route)] == route


def _belongs_to_group(
    cli_tokens: tuple[str, ...],
    routed_prefixes: Sequence[tuple[str, ...]],
) -> bool:
    """Return whether a registered command sits under one of the prefixes.

    A command whose canonical tokens hyphenate what reads as a group
    (``github-actions poll``) is routable spaced as well, so the prefix an
    operator types (``yoke github actions``) owns it even though no
    canonical token matches. The row still prints the canonical spelling —
    the one the CLI grammar guarantees and the one the usage line beneath
    it repeats.
    """
    spelled = [cli_tokens]
    spaced = tuple(part for token in cli_tokens for part in token.split("-"))
    if spaced in SPACE_EXPANDED_ROUTE_REGISTRY:
        spelled.append(spaced)
    return any(
        _extends(tokens, route)
        for tokens in spelled
        for route in routed_prefixes
    )


def emit_group_help_if_available(
    argv: Sequence[str], *, stream: Optional[TextIO] = None,
) -> Optional[int]:
    out = stream if stream is not None else sys.stdout
    help_requested = bool(argv) and argv[-1] in ("-h", "--help", "help")
    prefix = tuple(argv[:-1] if help_requested else argv)
    if not prefix:
        return None

    if prefix in GUIDANCE_ROUTES:
        print(GUIDANCE_ROUTES[prefix], file=out)
        return 0

    routed_prefixes = GROUP_ROUTES.get(prefix, (prefix,))

    rows: List[tuple[str, str, str]] = []
    registry_rows = {
        **SUBCOMMAND_REGISTRY,
        **SUBCOMMAND_ALIAS_REGISTRY,
    }
    for cli_tokens, (function_id, _adapter) in sorted(registry_rows.items()):
        if not _belongs_to_group(cli_tokens, routed_prefixes):
            continue
        cli_form = "yoke " + " ".join(cli_tokens)
        rows.append((cli_form, function_id, ADAPTER_USAGE.get(function_id, "")))

    tool_rows: List[tuple[str, str]] = []
    for cli_form, usage in sorted(TOOL_SHAPED_USAGE.items()):
        tokens = tuple(cli_form.split()[1:])
        if not any(_extends(tokens, route) for route in routed_prefixes):
            continue
        tool_rows.append((cli_form, usage))

    if not rows and not tool_rows:
        return None

    group = " ".join(prefix)
    print(f"yoke {group} - subcommand group.", file=out)
    print(file=out)
    print("Usage:", file=out)
    print(f"  yoke {group} <subcommand> [args...]", file=out)
    print(file=out)
    print("Available subcommands:", file=out)
    for cli_form, function_id, usage in rows:
        print(f"  {labeled_cli_form(cli_form)}", file=out)
        print(f"    -> {function_id}", file=out)
        if usage:
            print(f"    {usage}", file=out)
    for cli_form, usage in tool_rows:
        print(f"  {labeled_cli_form(cli_form)}", file=out)
        print("    -> client-local helper (no function id)", file=out)
        if usage:
            print(f"    {usage}", file=out)
    teaching = GROUP_TEACHING.get(prefix)
    if teaching:
        print(file=out)
        print(teaching.rstrip("\n"), file=out)
    print(file=out)
    print(FIELD_NOTE_FOOTER, file=out)
    return 0


def emit_nearest_group_help(
    argv: Sequence[str], *, stream: Optional[TextIO] = None,
) -> bool:
    """Print help for the longest prefix of ``argv`` that names a group.

    An unrecognised leaf under a real group (``yoke sessions heartbeat``)
    is answered with the group's actual members rather than a single fuzzy
    guess, so the next attempt is a choice from a list instead of another
    guess.
    """
    for length in range(len(argv) - 1, 0, -1):
        if emit_group_help_if_available(argv[:length], stream=stream) == 0:
            return True
    return False


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
    stripped = [token for token in argv if token not in ("-h", "--help", "help")]
    if not stripped:
        return None
    all_tokens = (
        tuple(SUBCOMMAND_REGISTRY)
        + tuple(SUBCOMMAND_ALIAS_REGISTRY)
        + tuple(SPACE_EXPANDED_ROUTE_REGISTRY)
        + tuple(TOOL_SHAPED_SUBCOMMANDS)
    )
    group = stripped[0]
    first_tokens = sorted({tokens[0] for tokens in all_tokens if tokens})
    # Sibling groups whose names differ from the typed one by a character
    # or two — `project` next to `projects` — are in scope, or the singular
    # spelling can only ever suggest its own members.
    siblings = set(get_close_matches(group, first_tokens, n=3, cutoff=0.8))
    # Hyphenated families whose last segment is the typed token —
    # `runs` next to `deployment-runs`.
    hyphen_families = {
        token for token in first_tokens
        if "-" in token and token.rsplit("-", 1)[-1] == group
    }
    candidates = [
        " ".join(tokens)
        for tokens in all_tokens
        if tokens and (
            tokens[0] == group
            or tokens[0].split("-")[0] == group
            or tokens[0] in siblings
            or tokens[0] in hyphen_families
        )
    ]
    candidates.extend(sorted(hyphen_families))
    if not candidates:
        return None
    requested = " ".join(stripped)
    matches = get_close_matches(requested, candidates, n=1, cutoff=0.35)
    if not matches:
        return None
    return f"Did you mean `yoke {matches[0]}`?"


__all__ = [
    "GROUP_ROUTES",
    "GROUP_TEACHING",
    "GUIDANCE_ROUTES",
    "can_route_group",
    "emit_group_help_if_available",
    "emit_nearest_group_help",
    "nearest_subcommand_hint",
]
