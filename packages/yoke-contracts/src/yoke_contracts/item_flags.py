"""Item flag predicates (blocked / frozen) — pure, client-tier.

``blocked`` and ``frozen`` are item-level display/routing flags, orthogonal to
lifecycle status. Hosted in yoke_contracts so board bucketing (and any client)
can read them without ``yoke_core``; ``yoke_core.domain.queries`` re-exports
them for its existing callers.
"""

from __future__ import annotations

from typing import Any


def _coerce_flag(value: Any) -> bool:
    """Return True when *value* represents a set (1/true) flag column."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value) in ("1", "true", "True")


def is_frozen(frozen_value: Any) -> bool:
    """Return True if *frozen_value* represents a frozen item."""
    return _coerce_flag(frozen_value)


def is_blocked(blocked_value: Any) -> bool:
    """Return True if *blocked_value* represents a blocked item.

    Blocked is an item-level routing/display flag (set via ``/yoke block`` or
    the idea path-claim fallback), independent of ``frozen`` and lifecycle
    ``status``.
    """
    return _coerce_flag(blocked_value)
