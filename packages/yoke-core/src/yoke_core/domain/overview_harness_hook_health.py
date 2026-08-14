"""Harness activation targets and their hook health.

A harness registers a session whether or not its hooks ever fire: the
CLI's ensure-register probe writes the same ``harness_sessions`` row a
hook-driven session start writes. Session presence alone therefore cannot
tell a working harness from one whose hook glue was never approved for the
project, and the broken one raises nothing — its signature is a session
that never accrues tool telemetry, so the board reads idle while the
session is in fact working and the next command cannot find it.

Hook health is the sub-signal that separates them. It reads the telemetry
columns only the hook chain stamps and reports, per target:

* ``not_seen`` — no session has ever matched the target;
* ``hooks_silent`` — sessions matched, none carry hook-written telemetry;
* ``hooks_live`` — at least one matching session does.

Unlike the activation latch beside it, health is live rather than
monotone: approval is re-keyed whenever the glue changes, so a target that
was ``hooks_live`` legitimately falls back to ``hooks_silent`` and the
remediation returns with it.

Health is reported only for harnesses that declare a hook-approval gate in
:mod:`yoke_contracts.harness_hook_approval`; a harness without one has no
approval to be missing, and nothing here branches on a harness id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from yoke_contracts.harness_hook_approval import hook_approval

HOOK_HEALTH_NOT_SEEN = "not_seen"
HOOK_HEALTH_SILENT = "hooks_silent"
HOOK_HEALTH_LIVE = "hooks_live"

#: How a target selects the sessions that belong to it.
MATCH_FAMILY = "family"
MATCH_BARE_SESSION = "bare_session"
MATCH_SURFACE_ALIAS = "surface_alias"

#: Target roster in render order: (key, label, harness id, match rule).
#: Family targets take every session of their harness; bare-session targets
#: take the ones that resolved no surface alias (the Claude/Codex CLI case);
#: surface-alias targets take the sessions whose alias is the target key
#: (Cursor stamps a surface, so its CLI target reads the alias too). Any one
#: session activates the module — targets are bonus decoration, never
#: blockers.
HARNESS_TARGETS: Tuple[Tuple[str, str, str, str], ...] = (
    ("claude-code", "Claude Code", "claude-code", MATCH_FAMILY),
    ("codex", "Codex", "codex", MATCH_FAMILY),
    ("cursor", "Cursor", "cursor", MATCH_FAMILY),
    ("claude-cli", "Claude CLI", "claude-code", MATCH_BARE_SESSION),
    ("codex-cli", "Codex CLI", "codex", MATCH_BARE_SESSION),
    ("cursor-cli", "Cursor CLI", "cursor", MATCH_SURFACE_ALIAS),
    ("claude-vscode", "Claude in VS Code", "claude-code", MATCH_SURFACE_ALIAS),
    ("cursor-desktop", "Cursor IDE", "cursor", MATCH_SURFACE_ALIAS),
)


def _matches(
    target: Tuple[str, str, str, str], executor: str, display: str,
) -> bool:
    key, _label, harness_id, rule = target
    if rule == MATCH_SURFACE_ALIAS:
        return display == key
    if executor != harness_id:
        return False
    return rule == MATCH_FAMILY or not display


def _health(matched: Sequence[Tuple[str, str, int]]) -> str:
    if not matched:
        return HOOK_HEALTH_NOT_SEEN
    if any(row[2] for row in matched):
        return HOOK_HEALTH_LIVE
    return HOOK_HEALTH_SILENT


def harness_targets(
    identities: Sequence[Tuple[str, str, int]],
) -> List[Dict[str, Any]]:
    """Render every target with its hit flag and hook health.

    ``identities`` are ``(executor, display, hook_fed_sessions)`` triples,
    one per distinct identity pair, from the activation read's single pass;
    ``hook_fed_sessions`` counts how many of those sessions carry
    hook-written tool telemetry.
    """
    targets: List[Dict[str, Any]] = []
    for target in HARNESS_TARGETS:
        key, label, harness_id, _rule = target
        matched = [
            row for row in identities if _matches(target, row[0], row[1])
        ]
        gate = hook_approval(harness_id)
        targets.append({
            "key": key,
            "label": label,
            "hit": bool(matched),
            "hook_health": None if gate is None else _health(matched),
            "trust_surface": None if gate is None else gate["trust_surface"],
        })
    return targets


__all__ = [
    "HARNESS_TARGETS",
    "HOOK_HEALTH_LIVE",
    "HOOK_HEALTH_NOT_SEEN",
    "HOOK_HEALTH_SILENT",
    "MATCH_BARE_SESSION",
    "MATCH_FAMILY",
    "MATCH_SURFACE_ALIAS",
    "harness_targets",
]
