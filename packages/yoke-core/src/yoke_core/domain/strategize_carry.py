"""Bounded carry-forward for Strategize landed-work review.

This module is the public import and ``python -m`` surface for the
responsibility-named carry modules:

* :mod:`yoke_core.domain.strategize_carry_schema`
* :mod:`yoke_core.domain.strategize_carry_state`
* :mod:`yoke_core.domain.strategize_carry_summary`
* :mod:`yoke_core.domain.strategize_carry_cli`
"""

from __future__ import annotations

from yoke_core.domain.strategize_carry_cli import main
from yoke_core.domain.strategize_carry_schema import (
    DEFAULT_CARRY_LIMIT,
    DEFAULT_HORIZON_DAYS,
    ensure_schema,
)
from yoke_core.domain.strategize_carry_state import (
    get_candidate_set,
    mark_items,
    register_new_landings,
)
from yoke_core.domain.strategize_carry_summary import format_summary

__all__ = [
    "DEFAULT_CARRY_LIMIT",
    "DEFAULT_HORIZON_DAYS",
    "ensure_schema",
    "format_summary",
    "get_candidate_set",
    "main",
    "mark_items",
    "register_new_landings",
]


if __name__ == "__main__":
    raise SystemExit(main())
