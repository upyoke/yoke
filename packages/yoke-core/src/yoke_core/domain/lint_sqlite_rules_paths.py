"""Compatibility alias for DB-command path policy fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_paths`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_paths import RULE_TEXT_WORKTREE_DB_PATH

__all__ = ("RULE_TEXT_WORKTREE_DB_PATH",)
