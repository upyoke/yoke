"""Replay of payloads recorded before definition metadata joined the queries.

A board payload recorded by an older build carries the item and epic-task
queries without the definition-metadata columns. Replay must still answer
those reads, padding the missing columns, rather than raising a parity miss.
"""

from __future__ import annotations

from yoke_contracts.board.sections_definition_queries import (
    _epic_task_rows_sql,
    _items_sql,
    _precomputed_epic_tasks_sql,
    query_epic_task_rows,
    query_item_rows,
    query_precomputed_epic_task_rows,
)
from yoke_core.board.data import BOARD_DATA_VERSION, ReplayBoardDB


def test_item_rows_fall_back_to_legacy_recorded_query():
    legacy_row = [
        7,
        "Legacy",
        "dash",
        "idea",
        "medium",
        0,
        0,
        7,
        "Yoke",
        "2026-08-03T00:00:00Z",
        "yoke",
        "YOK",
        7,
        "none",
    ]
    legacy_sql = _items_sql("", definition_metadata=False)
    replay = ReplayBoardDB.from_payload(
        {
            "version": BOARD_DATA_VERSION,
            "entries": [
                {
                    "kind": "query",
                    "sql": legacy_sql,
                    "params": None,
                    "rows": [legacy_row],
                }
            ],
        }
    )

    assert not replay.has_query(_items_sql("", definition_metadata=True))
    assert query_item_rows(replay, "") == [
        (*legacy_row[:-1], None, None, None, None, legacy_row[-1])
    ]


def test_epic_task_rows_fall_back_to_legacy_recorded_queries():
    detail_sql = _epic_task_rows_sql(definition_metadata=False)
    batch_sql = _precomputed_epic_tasks_sql("", definition_metadata=False)
    replay = ReplayBoardDB.from_payload(
        {
            "version": BOARD_DATA_VERSION,
            "entries": [
                {
                    "kind": "query",
                    "sql": detail_sql,
                    "params": [7],
                    "rows": [[1, "Task", "done"]],
                },
                {
                    "kind": "query_quiet",
                    "sql": batch_sql,
                    "params": None,
                    "rows": [[7, 1, "Task", "done"]],
                },
            ],
        }
    )

    assert query_epic_task_rows(replay, 7) == [(1, "Task", "done", None)]
    assert query_precomputed_epic_task_rows(replay, "") == [
        (7, 1, "Task", "done", None)
    ]
