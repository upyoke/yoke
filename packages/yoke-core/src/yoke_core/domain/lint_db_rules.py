"""Neutral assembly point for the Bash DB-command policy source.

``lint-sqlite-cmd`` remains the legacy stable telemetry/check id. This module
owns the implementation-facing name so non-SQLite policy checks (lifecycle
mutations, DDL, ``claude`` CLI, shell-shape guards, and raw ``sqlite3``
denials) are no longer classified as SQLite-only code.

The historical ``lint_sqlite_rules_*`` fragment modules remain importable as
legacy stable aliases, while this assembly consumes the neutral
``lint_db_rules_*`` names.
"""

from __future__ import annotations

# Recipe-event FOOTER attribution: the denial emit site lives in
# ``yoke_core.domain.lint_db_cmd`` and re-serializes the deny envelope with
# ``append_field_note_footer`` applied to the reason text, so every legacy
# stable ``lint-sqlite-cmd`` denial carries the FOOTER without each rule
# fragment below having to author it.
from yoke_core.domain.denial_field_note_footer import append_field_note_footer  # noqa: F401
from yoke_core.domain.lint_db_rules_columns import (
    RULE_TEXT_COLUMNS,
)
from yoke_core.domain.lint_db_rules_guards import (
    RULE_TEXT_BODY_BANS,
    RULE_TEXT_GUARDS_CLI,
    RULE_TEXT_GUARDS_INPUT,
)
from yoke_core.domain.lint_db_rules_lifecycle import (
    RULE_TEXT_ADD_PROJECT,
    RULE_TEXT_DONE,
    RULE_TEXT_LIFECYCLE,
)
from yoke_core.domain.lint_db_rules_operators import (
    RULE_TEXT_DDL_GATE,
    RULE_TEXT_OPERATORS_CMP,
    RULE_TEXT_SQLITE3,
)
from yoke_core.domain.lint_db_rules_paths import (
    RULE_TEXT_WORKTREE_DB_PATH,
)
from yoke_core.domain.lint_db_rules_preprocess import (
    RULE_TEXT_PREPROCESS,
)

# HOOK_POLICY_SOURCE assembly preserves the historical execution order.
# Each fragment is a self-contained source-text block; the runner exec's
# the concatenated result in a single fresh namespace, so names defined
# in earlier fragments (command_stripped, _LIFECYCLE_TABLES, ...) are
# available to later fragments without explicit injection.
HOOK_POLICY_SOURCE: str = (
    RULE_TEXT_PREPROCESS
    + RULE_TEXT_WORKTREE_DB_PATH
    + RULE_TEXT_GUARDS_INPUT
    + RULE_TEXT_SQLITE3
    + RULE_TEXT_GUARDS_CLI
    + RULE_TEXT_DONE
    + RULE_TEXT_BODY_BANS
    + RULE_TEXT_ADD_PROJECT
    + RULE_TEXT_LIFECYCLE
    + RULE_TEXT_DDL_GATE
    + RULE_TEXT_COLUMNS
    + RULE_TEXT_OPERATORS_CMP
)

__all__ = ("HOOK_POLICY_SOURCE",)
