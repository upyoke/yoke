"""Atlas-family grouping for the ``service_client --help`` umbrella.

The flat ``Commands: foo, bar, baz, ...`` listing the umbrella has
historically printed forces agents to read the source to learn which
family a subcommand belongs to. This module groups the registered
command names by Atlas family so the umbrella ``--help`` becomes a
discoverable map. New families and commands are added here; the family
order is the user-facing reading order.

Consumed by :mod:`yoke_core.api.service_client` from ``main()`` when the
caller asks for ``--help`` / ``-h`` / ``help`` at the umbrella level.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple


# (family_label, ordered_subcommand_prefix_or_exact_name_tuple).
# Matching is exact-name OR prefix-match (when the entry ends in ``-``)
# so a single ``path-claim-`` line covers every ``path-claim-*`` name.
_FAMILY_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Items / Backlog reads", (
        "active-queue", "item-list", "item-count", "item-get", "item-row",
        "item-progress", "item-next-id",
    )),
    ("Items / Backlog mutations", (
        "create-item", "validate-update", "update-item", "apply-approval",
        "execute-create-cli", "execute-create", "execute-update-cli",
        "execute-update", "execute-batch-update-cli", "execute-batch-update",
        "execute-close", "execute-structured-write",
    )),
    ("Backlog CLI surfaces", (
        "backlog-cli", "backlog-list-cli", "backlog-dedup-search",
        "backlog-github",
    )),
    ("Lifecycle / Gates", (
        "approve-check", "classify-status", "validate-status",
        "validate-transition", "evaluate-gate",
    )),
    ("Claims — work", (
        "claim-work", "release-work-claim", "claim-release",
        "release-all-claims", "release-done-claims",
    )),
    ("Claims — path", ("path-claim-",)),
    ("Coordination leases", ("coordination-lease-",)),
    ("Sessions", (
        "session-offer", "session-begin", "session-touch",
        "session-heartbeat", "session-end", "session-end-if-empty",
        "session-checkpoint", "session-checkpoint-read",
        "harness-capabilities", "clean-stale-sessions",
        "cleanup-never-engaged",
    )),
    ("Frontier / Routing", (
        "charge-frontier", "charge-schedule", "plan-candidates",
    )),
    ("Project Structure", ("project-structure-",)),
    ("Actors / DB claim", ("actors-get", "actors-list", "db-claim-amend")),
    ("Ouroboros", ("field-note-log",)),
    ("Ownership guard", ("ownership-guard",)),
)


def _match(command: str, pattern: str) -> bool:
    if pattern.endswith("-"):
        return command.startswith(pattern)
    return command == pattern


def group_commands(commands: Iterable[str]) -> List[Tuple[str, List[str]]]:
    """Return (family_label, [command, ...]) grouped by Atlas family.

    Commands not matching any declared family fall into an ``Other``
    bucket so new commands are discoverable until they get classified
    here. The ordering inside each family follows the declared pattern
    order, with any unmatched-but-claimed names appended alphabetically.
    """
    seen: set[str] = set()
    groups: List[Tuple[str, List[str]]] = []
    available = sorted(commands)
    for label, patterns in _FAMILY_GROUPS:
        bucket: List[str] = []
        for pattern in patterns:
            for cmd in available:
                if cmd in seen:
                    continue
                if _match(cmd, pattern):
                    bucket.append(cmd)
                    seen.add(cmd)
        if bucket:
            groups.append((label, bucket))
    leftover = [cmd for cmd in available if cmd not in seen]
    if leftover:
        groups.append(("Other", leftover))
    return groups


def render_umbrella_help(commands: Iterable[str]) -> str:
    """Render the canonical structured ``--help`` block for the umbrella.

    Includes a usage line, a worked example with a concrete ``YOK-N``,
    and the Atlas-family grouping.
    """
    lines: List[str] = []
    lines.append("Usage: python3 -m yoke_core.api.service_client <command> [args...]")
    lines.append("")
    lines.append("Run ``<command> --help`` for per-command worked examples.")
    lines.append("")
    lines.append("Worked example (acquire a typed work claim for an item):")
    lines.append("  python3 -m yoke_core.api.service_client claim-work \\")
    lines.append("    --item YOK-N --reason draft-in-progress")
    lines.append("")
    lines.append("Commands by Atlas family:")
    for label, bucket in group_commands(commands):
        lines.append(f"  {label}:")
        for cmd in bucket:
            lines.append(f"    {cmd}")
    return "\n".join(lines) + "\n"


__all__ = ["group_commands", "render_umbrella_help"]
