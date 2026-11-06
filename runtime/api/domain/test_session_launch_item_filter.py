"""Launch lists name the item each launch staffs and filter by it."""

from __future__ import annotations

from runtime.api.domain.session_launch_item_filter_test_support import (
    _list as _list,
    _named as _named,
    _seeded as _seeded,
    exercise_canonical_item_filter as exercise_canonical_item_filter,
    exercise_foreign_item_filter as exercise_foreign_item_filter,
)

from yoke_core.domain.session_launch_history_page import read_launch_page






def test_item_filter_keeps_only_launches_staffing_that_item() -> None:
    conn, ids = _seeded()
    page = read_launch_page(conn, project_id=10, item="YOK-12")
    assert [row["launch_id"] for row in page["operational"]] == [ids["live"]]
    assert [row["launch_id"] for row in page["history"]] == [ids["staffed"]]
    assert page["history_matched_count"] == 1
    assert {row["item"] for row in page["history"]} == {"YOK-12"}


def test_unfiltered_rows_carry_item_and_item_id() -> None:
    conn, ids = _seeded()
    rows = {
        row["launch_id"]: row
        for row in read_launch_page(conn, project_id=10)["history"]
    }
    assert rows[ids["longer"]]["item"] == "YOK-120"
    assert rows[ids["longer"]]["item_id"] == 420
    assert rows[ids["free"]]["item"] is None




def test_handler_filters_by_the_canonical_item_ref(monkeypatch) -> None:
    conn, ids = _seeded()
    outcome = _list(monkeypatch, conn, "yok-12")
    assert outcome.primary_success, outcome.error
    assert [row["launch_id"] for row in outcome.result_payload["history"]] == [
        ids["staffed"]
    ]


def test_handler_refuses_an_item_outside_the_project(monkeypatch) -> None:
    conn, _ids = _seeded()
    outcome = _list(monkeypatch, conn, "YOK-99999")
    assert not outcome.primary_success
    assert outcome.error.code == "item_not_found"
    assert "YOK-99999" in outcome.error.message
