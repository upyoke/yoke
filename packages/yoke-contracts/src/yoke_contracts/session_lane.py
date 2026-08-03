"""Shared execution-lane sentinel for harness sessions.

Every ``harness_sessions`` row carries an ``execution_lane``. When routing
policy resolves the session's executor to a configured lane, that lane name
is stored. When nothing matches, the row stores the sentinel below — which
is deliberately *not* a routable lane name: the lane gate treats it as an
unknown lane, so no work is offered on it until an operator declares the
lane or fixes the executor mapping.

Because the sentinel means "unresolved" rather than "a lane called
primary", it must never win against a configured executor mapping during
registration, and it must be visibly distinct wherever an operator reads a
lane.

Lives in ``yoke_contracts`` because both consumers need the same value and
neither may import the other: the engine's routing and registration paths
(``yoke_core``) and the board renderer (``yoke_contracts.board``).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


# Stored when no configured executor -> lane mapping matched.
UNRESOLVED_EXECUTION_LANE = "primary"

# Compatibility only: projects created before lane presentation became part of
# the session-routing capability still render exactly as they did before.
DEFAULT_LANE_METADATA: Mapping[str, Mapping[str, str]] = {
    "DARIUS": {"label": "DARIUS", "glyph": "\U0001f40e"},
    "ALTMAN": {"label": "ALTMAN", "glyph": "\U0001f453"},
}
LEGACY_LANE_PRESENTATION = DEFAULT_LANE_METADATA


def lane_is_unresolved(lane: Optional[str]) -> bool:
    """True when ``lane`` carries no resolved routing decision.

    Missing, blank, and sentinel values all mean the same thing — nothing
    resolved this session's lane — so every caller can ask one question
    instead of spelling out the pair. Matching folds case and surrounding
    whitespace so a hand-written ``PRIMARY`` in config, in an API request,
    or on the hook wire cannot smuggle the sentinel past a routing
    decision.
    """
    return (lane or "").strip().lower() in ("", UNRESOLVED_EXECUTION_LANE)


def lane_presentation(
    lane: Optional[str],
    settings: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """Resolve lane-owned label/glyph metadata with a legacy fallback."""
    lane_name = str(lane or "")
    configured: Mapping[str, Any] = {}
    if isinstance(settings, Mapping):
        all_metadata = settings.get("lane_metadata")
        if isinstance(all_metadata, Mapping):
            candidate = all_metadata.get(lane_name)
            if isinstance(candidate, Mapping):
                configured = candidate
    fallback = LEGACY_LANE_PRESENTATION.get(lane_name, {})
    return {
        "label": str(configured.get("label") or lane_name),
        "glyph": str(configured.get("glyph") or fallback.get("glyph") or ""),
    }


__all__ = [
    "DEFAULT_LANE_METADATA",
    "LEGACY_LANE_PRESENTATION",
    "UNRESOLVED_EXECUTION_LANE",
    "lane_is_unresolved",
    "lane_presentation",
]
