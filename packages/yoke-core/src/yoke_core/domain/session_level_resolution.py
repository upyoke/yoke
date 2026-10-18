"""Resolve current model/effort thresholds from observed facts and project Levels."""

from __future__ import annotations
from typing import Any, Optional, Sequence
from yoke_contracts.levels import Level, LevelsError, default_levels, level_for_session
from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL


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


def resolve_execution_level(
    *,
    executor: str,
    explicit_level: Optional[str],
    levels: Sequence[Level],
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    records: Sequence[Any] = (),
) -> str:
    """Resolve actual model facts; a launch's level stamp is never capability."""
    matched = level_for_session(
        levels,
        executor=executor,
        model=model,
        reasoning_effort=reasoning_effort,
        records=records,
    )
    return matched or UNRESOLVED_EXECUTION_LEVEL
