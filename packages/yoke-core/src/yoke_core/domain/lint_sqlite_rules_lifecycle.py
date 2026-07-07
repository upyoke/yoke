"""Compatibility alias for DB-command lifecycle-write policy fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_lifecycle`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_lifecycle import (
    RULE_TEXT_ADD_PROJECT,
    RULE_TEXT_DONE,
    RULE_TEXT_LIFECYCLE,
)

__all__ = (
    "RULE_TEXT_ADD_PROJECT",
    "RULE_TEXT_DONE",
    "RULE_TEXT_LIFECYCLE",
)
