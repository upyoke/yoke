"""Batched epic-task row tests for board section rendering."""

from __future__ import annotations

from yoke_contracts.board.sections import (
    ItemRow,
    precompute_epic_task_rows,
    render_section,
)
from runtime.api.board.tests.conftest import insert_item, insert_task


class TestPrecomputeEpicTaskRows:
    def test_batches_rows_by_scope(self, test_db):
        insert_item(test_db, 40, type="epic", project="yoke")
        insert_item(test_db, 41, type="epic", project="buzz")
        insert_task(test_db, 40, 1, "Yoke first", "done")
        insert_task(test_db, 40, 2, "Yoke second", "implementing")
        insert_task(test_db, 41, 1, "Buzz first", "done")

        result = precompute_epic_task_rows(test_db, "yoke")

        assert result == {
            40: [
                (1, "Yoke first", "done"),
                (2, "Yoke second", "implementing"),
            ]
        }

    def test_all_scope_includes_all_projects(self, test_db):
        insert_item(test_db, 50, type="epic", project="yoke")
        insert_item(test_db, 51, type="epic", project="buzz")
        insert_task(test_db, 50, 1, "Yoke first", "done")
        insert_task(test_db, 51, 1, "Buzz first", "done")

        result = precompute_epic_task_rows(test_db, "all")

        assert set(result) == {50, 51}


class TestRenderSectionPrecomputedEpicTaskRows:
    def test_section_with_precomputed_epic_subrows(self):
        class NoQueryDB:
            def query(self, *_args, **_kwargs):  # pragma: no cover
                raise AssertionError("render_section should use precomputed task rows")

        items = [
            ItemRow(
                3,
                "YOK-201",
                "My Epic",
                "epic",
                "medium",
                "implementing",
                "1/2 (50%)",
                201,
                "",
                "yoke",
                "2024-01-01",
            ),
        ]
        result = render_section(
            "Active",
            items,
            {201: 2},
            NoQueryDB(),
            "\U0001f535",
            7,
            {201: [(1, "Sub task 1", "done"), (2, "Sub task 2", "implementing")]},
        )

        corner_lines = [line for line in result.split("\n") if "└" in line]
        assert len(corner_lines) == 2
        assert "Sub task 1" in corner_lines[0]
        assert "Sub task 2" in corner_lines[1]
