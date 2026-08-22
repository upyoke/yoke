"""Inbound-executor canonicalization for ``register_session``.

Splits an inbound executor argument (and optional entrypoint) into the
``(canonical_executor, executor_surface)`` pair persisted by
``register_session``. Lives in a sibling module so
``sessions_lifecycle_registry.py`` stays under the 350-line cap.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_harness.hooks.identity import (
    canonical_harness_id,
    compose_executor_from_entrypoint,
)
from yoke_contracts.executor_labels import surface_alias

_LEGACY_CLAUDE_ALIAS = "claude"


def canonicalize_executor(
    executor: str,
    entrypoint: Optional[str],
) -> Tuple[str, Optional[str]]:
    """Split an inbound executor into the (canonical, display_name) pair.

    For known Yoke family executors (``claude-*`` / ``codex-*``), the
    canonical harness id is stored in ``harness_sessions.executor`` and the
    surface-specific alias is stored in ``executor_surface`` — or
    ``NULL`` when no surface-specific information is known. Surface
    preference order: a surface-specific ``executor`` argument wins; an
    entrypoint composed against a coarse executor argument is used next;
    otherwise the column stays NULL. Unrecognized family values are refused;
    the persisted executor vocabulary is closed.
    """
    try:
        canonical = canonical_harness_id(executor)
    except ValueError as exc:
        raise ValueError(
            f"unknown harness executor family: {executor!r}"
        ) from exc
    raw = (executor or "").strip().lower()
    if raw and raw != canonical and raw != _LEGACY_CLAUDE_ALIAS:
        return canonical, surface_alias(raw)
    if entrypoint:
        composed = compose_executor_from_entrypoint(executor, entrypoint)
        if composed and composed != canonical:
            return canonical, surface_alias(composed)
    return canonical, None


__all__ = ["canonicalize_executor"]
