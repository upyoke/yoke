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
        assert f"lint_db_rules_{suffix}" in module.__name__
        for symbol in _RULE_MODULES[suffix]:
            assert symbol in source
