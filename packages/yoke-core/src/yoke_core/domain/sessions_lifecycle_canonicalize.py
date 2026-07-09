"""Inbound-executor canonicalization for ``register_session``.

Splits an inbound executor argument (and optional entrypoint) into the
``(canonical_executor, executor_display_name)`` pair persisted by
``register_session``. Lives in a sibling module so
``sessions_lifecycle_registry.py`` stays under the 350-line cap.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_harness.hooks.identity import (
    canonical_harness_id,
    compose_executor_from_entrypoint,
)

_LEGACY_CLAUDE_ALIAS = "claude"


def canonicalize_executor(
    executor: str,
    entrypoint: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Split an inbound executor into the (canonical, display_name) pair.

    For known Yoke family executors (``claude-*`` / ``codex-*``), the
    canonical harness id is stored in ``harness_sessions.executor`` and the
    surface-specific alias is stored in ``executor_display_name`` — or
    ``NULL`` when no surface-specific information is known. Surface
    preference order: a surface-specific ``executor`` argument wins; an
    entrypoint composed against a coarse executor argument is used next;
    otherwise the column stays NULL. Unrecognized custom values pass
    through unchanged (the ``YOKE_EXECUTOR`` override path) and carry
    no display alias.
    """
    try:
        canonical = canonical_harness_id(executor)
    except ValueError:
        return executor, None
    raw = (executor or "").strip().lower()
    if raw and raw != canonical and raw != _LEGACY_CLAUDE_ALIAS:
        return canonical, raw
    if entrypoint:
        composed = compose_executor_from_entrypoint(executor, entrypoint)
        if composed and composed != canonical:
            return canonical, composed
    return canonical, None


__all__ = ["canonicalize_executor"]
