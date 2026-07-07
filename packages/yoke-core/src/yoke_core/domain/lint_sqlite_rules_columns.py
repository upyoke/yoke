"""Compatibility alias for DB-command column-name policy fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_columns`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_columns import RULE_TEXT_COLUMNS

__all__ = ("RULE_TEXT_COLUMNS",)
