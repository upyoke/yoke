"""Namespace-prefix help for registered ``yoke`` command groups."""

from __future__ import annotations

import sys
from difflib import get_close_matches
from typing import Optional, Sequence, TextIO

from yoke_cli.commands.command_summaries import summary_for
from yoke_cli.commands.command_tree import child_lines, listed_routes
from yoke_contracts.connection_authority_teaching import DB_GROUP_TEACHING

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
    ("deployment-runs",): (
        "Steering creates and drives release runs; member owners retain their "
        "item claims and credit their own scoped QA. Runs occupy their target "
        "servers, and only a live driver may continue its run.\n"
        "Recipes and prerequisites: yoke deployment-runs resolve-target --help.\n"
        "Execution and recovery: yoke watch deploy --help."
    ),
    ("env",): (
        "Selection: --env, YOKE_ENV, deepest registered checkout, unique "
        "--project or item-prefix reference, then active_env fallback. "
        "`yoke env use ENV` changes that fallback. "
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
    ("strategy", "doc"): (
        "Moving an item between strategy documents is an execution link, not "
        "a doc command: `yoke strategy execution link ITEM --project P "
        "--slug SLUG`."
    ),
    ("sessions",): (
        "Liveness: there is no standalone heartbeat command. "
        "`yoke sessions touch`, "
        "`yoke sessions checkpoint` each refresh the session's heartbeat."
    ),
}


def emit_group_help_if_available(
    argv: Sequence[str],
    *,
    stream: Optional[TextIO] = None,
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

    lines = child_lines(prefix) or sorted(
        {line for route in routed_prefixes for line in child_lines(route)}
    )
    if not lines:
        return None
    group = " ".join(prefix)
    if prefix == ("onboard",):
        print("For machine setup, run `yoke setup`.", file=out)
    print(f"yoke {group} - {summary_for(prefix)}", file=out)
    print(f"Usage: yoke {group} <subcommand> [arguments]", file=out)
    print("Immediate children (open --help for recipes and options):", file=out)
    print("\n".join(lines), file=out)
    teaching = GROUP_TEACHING.get(prefix)
    if teaching:
        print(file=out)
        print(teaching.rstrip("\n"), file=out)
    return 0


def emit_nearest_group_help(
    argv: Sequence[str],
    *,
    stream: Optional[TextIO] = None,
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
    """Return whether the CLI routes this exact spelling to useful guidance.

    A trailing ``--help`` on a group prefix routes to the same listing the
    bare prefix does, so it is the spelling teaching naturally uses for a
    group's deep home. Accept it rather than reading the flag as a
    subcommand that does not exist.
    """
    prefix = tuple(argv)
    if prefix and prefix[-1] in ("--help", "-h"):
        prefix = prefix[:-1]
    if not prefix:
        return False
    if prefix in GROUP_ROUTES or prefix in GUIDANCE_ROUTES:
        return True
    all_tokens = tuple(listed_routes())
    return any(
        len(tokens) > len(prefix) and tokens[: len(prefix)] == prefix
        for tokens in all_tokens
    )


def nearest_subcommand_hint(argv: Sequence[str]) -> str | None:
    """Suggest the nearest real member when an existing group is mistyped."""
    stripped = [token for token in argv if token not in ("-h", "--help", "help")]
    if not stripped:
        return None
    all_tokens = tuple(listed_routes())
    group = stripped[0]
    first_tokens = sorted({tokens[0] for tokens in all_tokens if tokens})
    # Sibling groups whose names differ from the typed one by a character
    # or two — `project` next to `projects` — are in scope, or the singular
    # spelling can only ever suggest its own members.
    siblings = set(get_close_matches(group, first_tokens, n=3, cutoff=0.8))
    # Hyphenated families whose last segment is the typed token —
    # `runs` next to `deployment-runs`.
    hyphen_families = {
        token
        for token in first_tokens
        if "-" in token and token.rsplit("-", 1)[-1] == group
    }
    candidates = [
        " ".join(tokens)
        for tokens in all_tokens
        if tokens
        and (
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
    # `sessions end` is the start of `sessions end-if-empty`, not a typo.
    prefixed = sorted({c for c in candidates if c.startswith(requested + "-")})
    if len(prefixed) == 1:
        return f"Did you mean `yoke {prefixed[0]}`?"
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
