"""Retired plan-limits table mark: compare headroom instead."""

_RETIRED_MARK = r"\b" + "tight" + "est" + r"\b"

PLAN_LIMIT_RETIREMENT_PATTERNS = (_RETIRED_MARK,)

PLAN_LIMIT_RETIREMENT_LABELS = {
    _RETIRED_MARK: ("retired plan-limits table mark (compare headroom across windows)"),
}

__all__ = [
    "PLAN_LIMIT_RETIREMENT_LABELS",
    "PLAN_LIMIT_RETIREMENT_PATTERNS",
]
