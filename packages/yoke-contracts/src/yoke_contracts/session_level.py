"""Shared execution-level sentinel for harness sessions.

Every ``harness_sessions`` row carries an ``execution_level``. When routing
policy resolves the session's executor to a configured level, that level name
is stored. When nothing matches, the row stores the sentinel below — which
means the session has no configured grouping. Work assignment follows
workflow bindings and explicit staffing independently of this grouping.

Because the sentinel means "unresolved" rather than "a level called
primary", it must never win against a configured executor mapping during
registration, and it must be visibly distinct wherever an operator reads a
level.

Lives in ``yoke_contracts`` because both consumers need the same value and
neither may import the other: the engine's routing and registration paths
(``yoke_core``) and the board renderer (``yoke_contracts.board``).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


# Stored when no configured executor -> level mapping matched.
UNRESOLVED_EXECUTION_LEVEL = "primary"

# Compatibility only: projects created before level presentation became part
# of the session-routing capability still render exactly as they did before.
DEFAULT_LEVEL_METADATA: Mapping[str, Mapping[str, str]] = {
    "DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"},
    "ALTMAN": {"label": "ALTMAN", "glyph": "\U0001f453"},
}
LEGACY_LEVEL_PRESENTATION = DEFAULT_LEVEL_METADATA

#: Session-routing keys retired by the lanes -> levels rename, each mapped to
#: the key that replaced it. Flat ``executor_default_lane_<executor>`` keys
#: are matched by prefix and replaced by ``executor_default_level_<executor>``.
RETIRED_ROUTING_KEYS: Mapping[str, str] = {
    "lane_metadata": "level_metadata",
    "lane_rules": "level_rules",
    "executor_default_lanes": "executor_default_levels",
}
RETIRED_EXECUTOR_DEFAULT_PREFIX = "executor_default_lane_"
EXECUTOR_DEFAULT_LEVEL_PREFIX = "executor_default_level_"


def level_is_unresolved(level: Optional[str]) -> bool:
    """True when ``level`` carries no resolved routing decision.

    Missing, blank, and sentinel values all mean the same thing — nothing
    resolved this session's level — so every caller can ask one question
    instead of spelling out the pair. Matching folds case and surrounding
    whitespace so a hand-written ``PRIMARY`` in config, in an API request,
    or on the hook wire cannot smuggle the sentinel past a routing
    decision.
    """
    return (level or "").strip().lower() in ("", UNRESOLVED_EXECUTION_LEVEL)


def retired_lane_setting_keys(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify removed action-permission keys for refusal and data convergence."""
    return tuple(
        key for key in settings if key == "lane_paths" or key.startswith("lane_paths_")
    )


def retired_process_offer_keys(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify removed process policy for write refusals and convergence."""
    return tuple(
        key
        for key in settings
        if key in {"process_offer", "process_offers"}
        or key.startswith("do_process_offer_")
    )


def renamed_routing_keys(settings: Mapping[str, Any]) -> dict[str, str]:
    """Map each retired routing key in ``settings`` to the key replacing it."""
    renamed: dict[str, str] = {}
    for key in settings:
        if key in RETIRED_ROUTING_KEYS:
            renamed[key] = RETIRED_ROUTING_KEYS[key]
        elif isinstance(key, str) and key.startswith(RETIRED_EXECUTOR_DEFAULT_PREFIX):
            suffix = key[len(RETIRED_EXECUTOR_DEFAULT_PREFIX) :]
            renamed[key] = f"{EXECUTOR_DEFAULT_LEVEL_PREFIX}{suffix}"
    return renamed


def level_presentation(
    level: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """Resolve level-owned label/glyph metadata with a legacy fallback."""
    level_name = str(level or "")
    configured: Mapping[str, Any] = {}
    if isinstance(settings, Mapping):
        all_metadata = settings.get("level_metadata")
        if isinstance(all_metadata, Mapping):
            candidate = all_metadata.get(level_name)
            if isinstance(candidate, Mapping):
                configured = candidate
    fallback = LEGACY_LEVEL_PRESENTATION.get(level_name, {})
    return {
        "label": str(configured.get("label") or level_name),
        "glyph": str(configured.get("glyph") or fallback.get("glyph") or ""),
    }


__all__ = [
    "DEFAULT_LEVEL_METADATA",
    "EXECUTOR_DEFAULT_LEVEL_PREFIX",
    "LEGACY_LEVEL_PRESENTATION",
    "RETIRED_EXECUTOR_DEFAULT_PREFIX",
    "RETIRED_ROUTING_KEYS",
    "UNRESOLVED_EXECUTION_LEVEL",
    "level_is_unresolved",
    "level_presentation",
    "renamed_routing_keys",
    "retired_lane_setting_keys",
    "retired_process_offer_keys",
]
