"""Compatibility alias for DB-command operator policy fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_operators`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_operators import (
    RULE_TEXT_DDL_GATE,
    RULE_TEXT_OPERATORS_CMP,
    RULE_TEXT_SQLITE3,
)

__all__ = (
    "RULE_TEXT_DDL_GATE",
    "RULE_TEXT_OPERATORS_CMP",
    "RULE_TEXT_SQLITE3",
)
