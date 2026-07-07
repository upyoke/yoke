"""Shared Yoke command/path capability registry.

Harness manifests describe identity and substrate limitations. They do not own
Yoke workflow or command semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


# The harness universe — every harness Yoke recognises. Used as the default
# `harness_support` value on `OperatorCommand` rows and consumed by the
# capability renderer plus capability-consistency tests so the universe is
# named in exactly one place.
HARNESS_UNIVERSE: tuple[str, ...] = ("claude-code", "codex")


@dataclass(frozen=True)
class OperatorCommand:
    """Operator-facing Yoke command metadata."""

    entrypoint: str
    display: str
    reminder: str
    harness_support: tuple[str, ...] = HARNESS_UNIVERSE


OPERATOR_COMMANDS: tuple[OperatorCommand, ...] = (
    OperatorCommand(
        "/yoke idea",
        "/yoke idea",
        "  /yoke idea   -- file a new backlog item",
    ),
    OperatorCommand(
        "/yoke do",
        "/yoke do",
        "  /yoke do     -- autonomous session orchestrator",
    ),
    OperatorCommand(
        "/yoke refine",
        "/yoke refine",
        "  /yoke refine -- critique and improve item artifacts",
    ),
    OperatorCommand(
        "/yoke advance",
        "/yoke advance YOK-N implementation",
        "  /yoke advance YOK-N implementation -- issue implementation entry",
    ),
    OperatorCommand(
        "/yoke polish",
        "/yoke polish",
        "  /yoke polish -- review and finish implementation in a worktree",
    ),
    OperatorCommand(
        "/yoke usher",
        "/yoke usher YOK-N [--dry-run]",
        "  /yoke usher YOK-N [--dry-run] -- merge/deploy handoff",
    ),
)

DOWNSTREAM_PATHS: tuple[str, ...] = (
    "shepherd",
    "refine",
    "advance",
    "polish",
    "usher",
)


# OPERATOR_COMMANDS above is the SESSION-OFFER REGISTRY: the entrypoints that
# /yoke do can route to. SAFE_OPERATOR_SURFACE below is the broader
# OPERATOR-FACING SURFACE: every /yoke command an operator can invoke
# directly, with per-harness compat metadata. Kept as siblings (not unified)
# because they answer different questions: "which entrypoints does the
# session-offer machinery orchestrate?" vs. "which commands is a harness
# allowed to run?". Drift between either of these and the docs that enumerate
# them is locked by tests in runtime/api/test_capability_consistency.py.
SAFE_OPERATOR_SURFACE: tuple[OperatorCommand, ...] = (
    OperatorCommand(
        "/yoke idea",
        "/yoke idea",
        "  /yoke idea       -- file a new backlog item",
    ),
    OperatorCommand(
        "/yoke shepherd",
        "/yoke shepherd YOK-N",
        "  /yoke shepherd YOK-N -- drive item through quality-gated lifecycle to planned",
    ),
    OperatorCommand(
        "/yoke conduct",
        "/yoke conduct YOK-N",
        "  /yoke conduct YOK-N -- engineer/tester loop for a single item or epic",
    ),
    OperatorCommand(
        "/yoke advance",
        "/yoke advance YOK-N implementation",
        "  /yoke advance YOK-N implementation -- issue implementation entry",
    ),
    OperatorCommand(
        "/yoke usher",
        "/yoke usher YOK-N [--dry-run]",
        "  /yoke usher YOK-N [--dry-run] -- merge/deploy handoff",
    ),
    OperatorCommand(
        "/yoke doctor",
        "/yoke doctor [project]",
        "  /yoke doctor [project] -- health checks and diagnostics",
    ),
    OperatorCommand(
        "/yoke freeze",
        "/yoke freeze YOK-N",
        "  /yoke freeze YOK-N -- freeze an item",
    ),
    OperatorCommand(
        "/yoke thaw",
        "/yoke thaw YOK-N",
        "  /yoke thaw YOK-N -- thaw a frozen item",
    ),
    OperatorCommand(
        "/yoke block",
        "/yoke block YOK-N \"<reason>\"",
        "  /yoke block YOK-N \"<reason>\" -- block an item (preserves status)",
    ),
    OperatorCommand(
        "/yoke unblock",
        "/yoke unblock YOK-N",
        "  /yoke unblock YOK-N -- clear an item's blocked flag",
    ),
    OperatorCommand(
        "/yoke resync",
        "/yoke resync",
        "  /yoke resync   -- detect and repair GitHub drift",
    ),
    OperatorCommand(
        "/yoke curate",
        "/yoke curate",
        "  /yoke curate   -- curate the Ouroboros learning log",
    ),
    OperatorCommand(
        "/yoke wrapup",
        "/yoke wrapup",
        "  /yoke wrapup   -- structured session wrap-up",
    ),
    OperatorCommand(
        "/yoke refine",
        "/yoke refine YOK-N",
        "  /yoke refine YOK-N -- critique and improve item artifacts",
    ),
    OperatorCommand(
        "/yoke polish",
        "/yoke polish YOK-N",
        "  /yoke polish YOK-N -- review and finish implementation",
    ),
    OperatorCommand(
        "/yoke help",
        "/yoke help",
        "  /yoke help     -- show command reference",
    ),
    OperatorCommand(
        "/yoke do",
        "/yoke do",
        "  /yoke do       -- autonomous session orchestrator",
    ),
    OperatorCommand(
        "/yoke charge",
        "/yoke charge",
        "  /yoke charge   -- pick up next runnable item from frontier",
    ),
    OperatorCommand(
        "/yoke feed",
        "/yoke feed",
        "  /yoke feed     -- refresh frontier and materialize ideas",
    ),
    OperatorCommand(
        "/yoke strategize",
        "/yoke strategize",
        "  /yoke strategize -- guided Strategic Markdown Layer review",
    ),
)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def shared_entrypoints() -> list[str]:
    """Return shared Yoke operator entrypoint ids."""
    return [command.entrypoint for command in OPERATOR_COMMANDS]


def shared_downstream_paths() -> list[str]:
    """Return shared Yoke downstream path ids."""
    return list(DOWNSTREAM_PATHS)


def safe_operator_surface() -> list[OperatorCommand]:
    """Return the full operator command surface (all 19 commands)."""
    return list(SAFE_OPERATOR_SURFACE)


def safe_operator_surface_for_harness(harness_id: str) -> list[OperatorCommand]:
    """Return safe operator surface entries supported by the given harness."""
    return [c for c in SAFE_OPERATOR_SURFACE if harness_id in c.harness_support]


def safe_operator_surface_entrypoints(harness_id: str) -> list[str]:
    """Return entrypoint ids from the safe operator surface filtered by harness."""
    return [c.entrypoint for c in safe_operator_surface_for_harness(harness_id)]


def manifest_disabled_entrypoints(manifest: Mapping[str, Any]) -> list[str]:
    """Return manifest-declared command limitations."""
    supports = manifest.get("supports", {})
    if not isinstance(supports, Mapping):
        return []
    return _string_list(supports.get("disabled_entrypoints"))


def manifest_disabled_downstream_paths(manifest: Mapping[str, Any]) -> list[str]:
    """Return manifest-declared downstream path limitations."""
    supports = manifest.get("supports", {})
    if not isinstance(supports, Mapping):
        return []
    return _string_list(supports.get("disabled_downstream_paths"))


def entrypoints_for_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Return shared entrypoints after applying manifest limitations."""
    disabled = set(manifest_disabled_entrypoints(manifest))
    return [item for item in shared_entrypoints() if item not in disabled]


def downstream_paths_for_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Return shared downstream paths after applying manifest limitations."""
    disabled = set(manifest_disabled_downstream_paths(manifest))
    return [item for item in shared_downstream_paths() if item not in disabled]


def ordered_commands(entrypoints: Sequence[str]) -> list[OperatorCommand]:
    """Return command metadata in registry order, preserving unknown ids."""
    by_entrypoint = {command.entrypoint: command for command in OPERATOR_COMMANDS}
    known = [command for command in OPERATOR_COMMANDS if command.entrypoint in entrypoints]
    extras = [
        OperatorCommand(item, item, f"  {item}")
        for item in entrypoints
        if item not in by_entrypoint
    ]
    return known + extras


def compact_entrypoint_display(entrypoints: Sequence[str] | None = None) -> str:
    """Render a compact command list for startup orientation."""
    selected = entrypoints or shared_entrypoints()
    return ", ".join(command.display for command in ordered_commands(selected))


def prompt_reminder_lines(entrypoints: Sequence[str] | None = None) -> list[str]:
    """Render prompt reminder lines for supported entrypoints."""
    selected = entrypoints or shared_entrypoints()
    return [command.reminder for command in ordered_commands(selected)]
