"""Launch-list tests must leave fresh imports using the real item lookup."""

from __future__ import annotations

import importlib
import sqlite3
import sys

import pytest

from runtime.api.domain import test_session_launch_item_filter as item_filter
from yoke_core import domain


@pytest.mark.parametrize("preload", [False, True], ids=["list-first", "entry-first"])
@pytest.mark.parametrize(
    "exercise",
    [
        item_filter.test_handler_filters_by_the_canonical_item_ref,
        item_filter.test_handler_refuses_an_item_outside_the_project,
    ],
    ids=["canonical", "missing"],
)
def test_launch_list_test_preserves_work_entry_resolution(monkeypatch, preload, exercise):
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
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, slug TEXT, name TEXT, public_item_prefix TEXT
            );
            INSERT INTO projects VALUES (10, 'launch-project', 'Launch project', 'YOK');
            CREATE TABLE items (id INTEGER, project_id INTEGER, project_sequence INTEGER);
            INSERT INTO items VALUES (731, 10, 12);
            """
        )
        assert work_entry.resolve_item_ref_or_none(conn, "YOK-12", project=10) == 731
        assert work_entry.resolve_item_ref_or_none(conn, "YOK-99999", project=10) is None
