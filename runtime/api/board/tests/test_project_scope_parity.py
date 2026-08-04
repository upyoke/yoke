"""Project-scope query-shape and replay diagnostics regressions."""

from __future__ import annotations

import pytest

from yoke_contracts.board.data import BoardDataMissError, ReplayBoardDB
from yoke_contracts.board.project_scope import project_filter


def test_replay_miss_names_parameter_difference():
    sql = "SELECT id FROM items WHERE project_id = %s"
    replay = ReplayBoardDB.from_payload(
        {
            "version": 1,
            "entries": [
                {
                    "kind": "query",
                    "sql": sql,
                    "params": [1],
                    "rows": [],
                }
            ],
        }
    )

    with pytest.raises(
        BoardDataMissError,
        match=r"SQL matched but parameters differed: recorded=\[\[1\]\], replay=\(2,\)",
    ):
        replay.query(sql, (2,))


def test_project_scope_changes_parameters_not_query_shape():
    first_sql, first_params = project_filter("yoke", "i")
    second_sql, second_params = project_filter("externalwebapp", "i")

    assert first_sql == second_sql
    assert first_params == ("yoke",)
    assert second_params == ("externalwebapp",)
    assert "yoke" not in first_sql
    assert "externalwebapp" not in second_sql
