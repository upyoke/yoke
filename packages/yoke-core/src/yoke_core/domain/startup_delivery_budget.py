"""Measure the instruction payload each harness surface actually receives.

The packet budgets in :mod:`schema_api_context_packet_budget` bound one
generated artifact. They cannot answer the question that matters at session
start, which is whether the *combined* text a surface is handed fits in the
channel carrying it. A packet inside its own budget still arrives truncated
when the block it rides is many times the harness's inline ceiling.

This module composes that combined figure per harness, one row per channel
named in :mod:`yoke_contracts.startup_context_budget`:

``root_rules``
    the rules files the harness reads from disk before its first turn;
``inline_hook``
    the startup orientation block returned through ``additionalContext``;
``agent_prompt``
    the largest rendered subagent body, with every body listed beside it.

Surfaces are reported rather than assumed away: a harness family's CLI and
desktop surfaces read the same rules files and share one inline ceiling —
neither the hook composer nor the rules loader consults the surface — so the
two carry one payload, and each row names the surfaces it covers instead of
leaving a reader to wonder whether the desktop case was measured.

Read-only. Every path resolves under an explicit *target_root* so the report
describes the checkout the caller names rather than an ambient cwd.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from yoke_contracts.executor_labels import EXECUTOR_EMOJI, canonical_harness_id
from yoke_contracts.project_contract.installed_layer import CLAUDE_RULES_DEST
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_contracts.startup_context_budget import (
    budget_phrase,
    estimated_tokens,
    root_rules_bytes,
)
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.install_bundle import CLAUDE_RULES_SOURCE
from yoke_core.domain.agents_render_conditional import (
    HARNESS_IDS,
    rendered_agents_dir,
)


# The rules files each harness reads before its first turn, per harness, as
# ordered candidate paths: the first one that exists is the one measured.
#
# Two layouts have to resolve, because the same report runs in both. A Yoke
# source checkout keeps the Claude session rules under the renderer's source
# path and exposes ``.claude/rules`` as a symlink to it; an installed project
# has no ``runtime/`` tree at all and carries the bundle's real file at the
# installed path. Measuring only the source path would silently report zero
# bytes for that contributor in every external checkout — understating the
# channel exactly where the rules are most likely to be over it.
#
# The two paths come from the mapping the installer already owns rather than
# from literals here, so a move cannot leave this measurement behind.
ROOT_RULES_SOURCES: dict[str, tuple[tuple[str, ...], ...]] = {
    "claude": (
        ("AGENTS.md",),
        (
            f"{CLAUDE_RULES_SOURCE}/session.md",
            f"{CLAUDE_RULES_DEST}/session.md",
        ),
    ),
    "codex": (("AGENTS.md",),),
    "cursor": (("AGENTS.md",),),
}

# The command that reports this measurement, named in every refusal so the
# discovery path stays one command.
DELIVERY_READ_COMMAND = "yoke packets startup-delivery get"


__all__ = [
    "DELIVERY_READ_COMMAND",
    "ROOT_RULES_SOURCES",
    "startup_delivery_report",
    "surfaces_for_harness",
]


def surfaces_for_harness(harness_id: str) -> tuple[str, ...]:
    """Return the known executor surfaces one payload is delivered to."""
    return tuple(
        sorted(
            label
            for label in EXECUTOR_EMOJI
            if label.startswith(f"{harness_id}-")
            and label != f"{harness_id}-code"
        )
    )


def _read_bytes(path: Path) -> int:
    try:
        return len(path.read_bytes())
    except OSError:
        return 0


def _channel_row(
    channel: str,
    *,
    harness_id: str,
    used: int,
    budget: int,
    contributors: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "channel": channel,
        "harness_id": harness_id,
        "surfaces": list(surfaces_for_harness(harness_id)),
        "bytes": used,
        "budget": budget,
        "headroom": budget - used,
        "estimated_tokens": estimated_tokens(used),
        "over_budget": used > budget,
        "contributors": contributors,
    }


def _root_rules_row(harness_id: str, target_root: Path) -> Dict[str, Any]:
    """Measure one harness's rules channel, naming the path it resolved.

    A candidate group that resolves nowhere is reported as ``resolved: false``
    with the paths tried, rather than folded into the total as zero bytes: a
    contributor nobody can find is a gap in the measurement, and a silent zero
    reads as headroom.
    """
    contributors: List[Dict[str, Any]] = []
    total = 0
    for candidates in ROOT_RULES_SOURCES[harness_id]:
        found = next(
            (rel for rel in candidates if (target_root / rel).is_file()), None
        )
        if found is None:
            contributors.append(
                {"path": " | ".join(candidates), "bytes": 0, "resolved": False}
            )
            continue
        size = _read_bytes(target_root / found)
        total += size
        contributors.append({"path": found, "bytes": size, "resolved": True})
    return _channel_row(
        "root_rules",
        harness_id=harness_id,
        used=total,
        budget=root_rules_bytes(harness_id),
        contributors=contributors,
    )


def _inline_hook_row(harness_id: str, orientation_bytes: int) -> Dict[str, Any]:
    return _channel_row(
        "inline_hook",
        harness_id=harness_id,
        used=orientation_bytes,
        budget=inline_context_bytes_for_harness(canonical_harness_id(harness_id)),
        contributors=[
            {"path": "session orientation block", "bytes": orientation_bytes}
        ],
    )


def _agent_prompt_row(harness_id: str, target_root: Path) -> Dict[str, Any]:
    directory = target_root / rendered_agents_dir(harness_id)
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        entries = []
    contributors = [
        {
            "path": entry.relative_to(target_root).as_posix(),
            "bytes": _read_bytes(entry),
        }
        for entry in entries
        if entry.is_file()
    ]
    return _channel_row(
        "agent_prompt",
        harness_id=harness_id,
        used=max((row["bytes"] for row in contributors), default=0),
        budget=seed.AGENT_PROMPT_BYTE_BUDGET,
        contributors=contributors,
    )


def _orientation_bytes(target_root: Path) -> int:
    """Return the delivered size of one rendered startup orientation block.

    Rendered for real rather than approximated: the block carries the
    machine-local advisories and git lines a synthetic estimate would miss,
    and those bytes are delivered like any other.
    """
    from yoke_core.domain.session_orientation import render_orientation

    block = render_orientation(
        {"session_id": "00000000-0000-0000-0000-000000000000"}, target_root
    )
    return len(block.encode("utf-8"))


def startup_delivery_report(target_root: Path) -> Dict[str, Any]:
    """Return every startup channel's usage against its budget, per harness."""
    root = Path(target_root)
    orientation_bytes = _orientation_bytes(root)
    channels: List[Dict[str, Any]] = []
    for harness_id in sorted(HARNESS_IDS):
        channels.extend(
            (
                _root_rules_row(harness_id, root),
                _inline_hook_row(harness_id, orientation_bytes),
                _agent_prompt_row(harness_id, root),
            )
        )
    return {
        "target_root": str(root),
        "channels": channels,
        "over_budget": [
            f"{row['harness_id']} {row['channel']} spends "
            f"{budget_phrase(row['bytes'], row['budget'])}"
            for row in channels
            if row["over_budget"]
        ],
    }
