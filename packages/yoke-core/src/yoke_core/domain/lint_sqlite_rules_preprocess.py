"""Compatibility alias for DB-command payload preprocessing fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_preprocess`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_preprocess import RULE_TEXT_PREPROCESS

__all__ = ("RULE_TEXT_PREPROCESS",)
