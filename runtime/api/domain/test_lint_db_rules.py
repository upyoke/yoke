"""Neutral DB-command rule ownership tests."""

from __future__ import annotations

import importlib
import inspect


_RULE_MODULES = {
    "columns": ("RULE_TEXT_COLUMNS",),
    "guards": (
        "RULE_TEXT_BODY_BANS",
        "RULE_TEXT_GUARDS_CLI",
        "RULE_TEXT_GUARDS_INPUT",
    ),
    "lifecycle": (
        "RULE_TEXT_ADD_PROJECT",
        "RULE_TEXT_DONE",
        "RULE_TEXT_LIFECYCLE",
    ),
    "operators": (
        "RULE_TEXT_DDL_GATE",
        "RULE_TEXT_OPERATORS_CMP",
        "RULE_TEXT_SQLITE3",
    ),
    "paths": ("RULE_TEXT_WORKTREE_DB_PATH",),
    "preprocess": ("RULE_TEXT_PREPROCESS",),
}


def test_lint_db_rule_modules_own_live_fragments() -> None:
    for suffix in _RULE_MODULES:
        module = importlib.import_module(
            f"yoke_core.domain.lint_db_rules_{suffix}"
        )
        source = inspect.getsource(module)
        assert "from yoke_core.domain.lint_sqlite_rules" not in source


def test_lint_sqlite_rule_modules_remain_legacy_aliases() -> None:
    for suffix, symbols in _RULE_MODULES.items():
        neutral = importlib.import_module(
            f"yoke_core.domain.lint_db_rules_{suffix}"
        )
        legacy = importlib.import_module(
            f"yoke_core.domain.lint_sqlite_rules_{suffix}"
        )
        for symbol in symbols:
            assert getattr(legacy, symbol) is getattr(neutral, symbol)
