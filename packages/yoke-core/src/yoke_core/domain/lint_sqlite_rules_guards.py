"""Compatibility alias for DB-command shell-shape guard fragments.

The implementation-facing owner is
:mod:`yoke_core.domain.lint_db_rules_guards`. This legacy module remains
importable for historical ``lint_sqlite_rules_*`` callers.
"""

from __future__ import annotations

from yoke_core.domain.lint_db_rules_guards import (
    RULE_TEXT_BODY_BANS,
    RULE_TEXT_GUARDS_CLI,
    RULE_TEXT_GUARDS_INPUT,
)

__all__ = (
    "RULE_TEXT_BODY_BANS",
    "RULE_TEXT_GUARDS_CLI",
    "RULE_TEXT_GUARDS_INPUT",
)
