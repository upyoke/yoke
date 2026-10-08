"""Resolve the execution level a registering session is stamped with.

A session's level comes from the levels its project reads (the project's
``session-routing`` override, else the universe definition, else the shipped
scheme): the first level, lowest first, holding an option that matches the
session's harness, model, and effort. See :mod:`yoke_contracts.levels`.

The machine ``key=value`` config helpers here serve other machine settings;
the machine config carries no level routing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from yoke_contracts.levels import Level, LevelsError, default_levels, level_for_session
from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL, level_is_unresolved
from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_SUFFIX
from yoke_core.domain import runtime_settings


def parse_config_file(config_path: str | Path) -> Dict[str, str]:
    """Parse the Yoke ``key=value`` config file into a raw dict."""
    return runtime_settings.read_all(config_path=Path(config_path))


def session_levels(conn: Any, project_id: Optional[int]) -> tuple[Level, ...]:
    """Return the levels a session in ``project_id`` is labeled against.

    Stored documents are validated at write time; one that no longer reads
    (a raw edit) labels nothing rather than refusing every registration,
    and ``yoke projects level-summary get`` names the repair.
    """
    if conn is None:
        return default_levels()
    from yoke_core.domain.universe_levels import UniverseLevelsError, effective_levels

    try:
        return effective_levels(conn, project_id)[0]
    except (LevelsError, UniverseLevelsError):
        return ()


def routing_model_of(
    served_model: Optional[str], requested_model: Optional[str]
) -> Optional[str]:
    """Return the model an option is matched against.

    A provider-attested model wins. Most sessions have none at registration,
    so the ask is the fallback, with its context-tier suffix removed because
    that suffix names a context window rather than a different model.
    """
    if served_model and served_model.strip():
        return served_model.strip()
    asked = (requested_model or "").strip()
    if asked.lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        asked = asked[: -len(CLAUDE_CONTEXT_TIER_SUFFIX)]
    return asked or None


def routing_effort_of(
    served_effort: Optional[str], requested_effort: Optional[str]
) -> Optional[str]:
    """Return the effort an option is matched against, attested first."""
    for value in (served_effort, requested_effort):
        if value and value.strip():
            return value.strip().lower()
    return None


def resolve_execution_level(
    *,
    executor: str,
    explicit_level: Optional[str],
    levels: Sequence[Level],
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> str:
    """Resolve the level a registering session is stamped with.

    An explicit level wins only when it names a real choice: ``default`` and
    the unresolved sentinel both mean "nothing chose a level" and yield to
    the option match. ``model`` is the model the session serves; with none
    attested no option can match and the session stays unresolved.
    """
    if explicit_level and explicit_level.strip():
        resolved = explicit_level.strip()
        if resolved.lower() != "default" and not level_is_unresolved(resolved):
            return resolved
    matched = level_for_session(
        levels, executor=executor, model=model, reasoning_effort=reasoning_effort
    )
    return matched or UNRESOLVED_EXECUTION_LEVEL


def config_path_from_db_path(db_path: str | Path) -> Path:
    """Return the legacy fixture config path adjacent to an explicit test DB."""
    return Path(db_path).resolve().parent / "config"
