"""Launch-list tests must leave fresh imports using the real item lookup."""

from __future__ import annotations

import importlib
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from runtime.api.domain import session_launch_item_filter_test_support as item_filter
from yoke_core import domain
from yoke_contracts.timestamps import parse_instant


@pytest.mark.parametrize("preload", [False, True], ids=["list-first", "entry-first"])
@pytest.mark.parametrize(
    "exercise",
    [
        item_filter.exercise_canonical_item_filter,
        item_filter.exercise_foreign_item_filter,
    ],
    ids=["canonical", "missing"],
)
def test_launch_list_test_preserves_work_entry_resolution(
    monkeypatch, preload, exercise
):
    module_name = "yoke_core.domain.session_launch_work_entry"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delattr(domain, "session_launch_work_entry", raising=False)
    if preload:
        importlib.import_module(module_name)
    with pytest.MonkeyPatch.context() as scoped:
        exercise(scoped)
    work_entry = importlib.import_module(module_name)

    with sqlite3.connect(":memory:") as conn:
        conn.executescript(
            """
            CREATE TABLE work_claims (
                session_id TEXT, target_kind TEXT, scope TEXT, claimed_at TEXT
            );
            """
        )
        launch = SimpleNamespace(
            item_id=731,
            registered_session_id="worker",
            launching_at=parse_instant("2026-11-05T10:00:00Z"),
            deadline_at=parse_instant("2026-11-05T11:00:00Z"),
        )
        assert not work_entry.launch_work_entered(conn, launch)
        conn.execute(
            "INSERT INTO work_claims VALUES ('worker','item',?,?)",
            ('{"item_id": 732}', "2026-11-05T10:01:00Z"),
        )
        assert not work_entry.launch_work_entered(conn, launch)
        conn.execute(
            "INSERT INTO work_claims VALUES ('worker','item',?,?)",
            ('{"item_id": 731}', "2026-11-05T10:02:00Z"),
        )
        assert work_entry.launch_work_entered(conn, launch)
