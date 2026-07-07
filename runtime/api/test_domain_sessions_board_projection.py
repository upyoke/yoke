"""Board projection tests for yoke_core.domain.board."""

from __future__ import annotations

from yoke_core.domain.lifecycle import BOARD_COLUMN_ORDER

from yoke_core.domain.board import (
    BOARD_COLUMNS,
    BoardProjection,
    ItemForBoard,
    project_board,
)


class TestItemForBoard:
    """Test ItemForBoard dataclass (task 005)."""

    def test_item_type_default_none(self):
        """AC-9: ItemForBoard has optional item_type field (default None)."""
        ifb = ItemForBoard(item={"id": 1}, status="implementing")
        assert ifb.item_type is None

    def test_item_type_set(self):
        """AC-9: ItemForBoard accepts item_type."""
        ifb = ItemForBoard(item={"id": 1}, status="implementing", item_type="epic")
        assert ifb.item_type == "epic"


class TestBoardProjection:
    """Test board projection logic."""

    def test_empty_board(self):
        board = BoardProjection.empty(project="yoke")
        assert board.project == "yoke"
        assert board.columns == {}
        assert board.stats.total == 0
        assert board.stats.done == 0
        assert board.stats.active == 0
        assert board.stats.remaining == 0


class TestProjectBoard:
    """Test the project_board() function for grouping and stats."""

    def _make_item(
        self,
        item_id: int,
        status: str,
        frozen: int = 0,
        has_active_run: bool = False,
        item_type: str | None = None,
    ) -> ItemForBoard:
        return ItemForBoard(
            item={"id": item_id, "status": status},
            status=status,
            frozen_value=frozen,
            has_active_run=has_active_run,
            item_type=item_type,
        )

    def test_basic_grouping(self):
        items = [
            self._make_item(1, "implementing"),
            self._make_item(2, "done"),
            self._make_item(3, "idea"),
            self._make_item(4, "planned"),
        ]
        board = project_board(items, project="yoke")
        assert board.project == "yoke"
        assert len(board.columns["implementing"]) == 1
        assert len(board.columns["done"]) == 1
        assert len(board.columns["idea"]) == 1
        assert len(board.columns["refined"]) == 1
        assert board.stats.total == 4
        assert board.stats.done == 1
        assert board.stats.active == 1
        assert board.stats.remaining == 2

    def test_frozen_items_excluded(self):
        items = [
            self._make_item(1, "implementing"),
            self._make_item(2, "implementing", frozen=1),
        ]
        board = project_board(items)
        assert len(board.columns["implementing"]) == 1
        assert board.stats.total == 1
        assert board.stats.active == 1

    def test_status_mapping_in_projection(self):
        """Verify that status-to-bucket rules apply during projection."""
        items = [
            self._make_item(1, "reviewing-implementation"),  # -> reviewing
            self._make_item(2, "planned"),  # -> refined
            self._make_item(3, "refined-idea"),  # -> refined
            self._make_item(4, "stopped"),     # -> blocked
            self._make_item(5, "failed"),      # -> blocked
            self._make_item(6, "cancelled"),   # -> done
        ]
        board = project_board(items)
        assert len(board.columns["reviewing"]) == 1
        assert len(board.columns["refined"]) == 2
        assert len(board.columns["blocked"]) == 2
        assert len(board.columns["done"]) == 1

    def test_fr7_active_run_upgrade(self):
        """FR-7: implemented + active-run -> release in board projection."""
        items = [
            self._make_item(1, "implemented", has_active_run=True),
            self._make_item(2, "implemented", has_active_run=False),
        ]
        board = project_board(items)
        assert len(board.columns["release"]) == 1
        assert len(board.columns["implemented"]) == 1

    def test_empty_items_board(self):
        """Empty items board should have all empty columns."""
        board = project_board([], project="yoke")
        for col in BOARD_COLUMNS:
            assert board.columns[col] == []
        assert board.stats.total == 0

    def test_stats_calculation(self):
        items = [
            self._make_item(1, "implementing"),
            self._make_item(2, "implementing"),
            self._make_item(3, "done"),
            self._make_item(4, "idea"),
            self._make_item(5, "reviewed-implementation"),
        ]
        board = project_board(items)
        assert board.stats.total == 5
        assert board.stats.done == 1
        assert board.stats.active == 2
        assert board.stats.remaining == 2  # 5 - 1 - 2

    def test_all_board_columns_present(self):
        board = project_board([])
        for col in BOARD_COLUMNS:
            assert col in board.columns

    def test_unknown_status_excluded_from_board(self):
        items = [
            ItemForBoard(item={"id": 1}, status="bogus_status"),
        ]
        board = project_board(items)
        assert board.stats.total == 0  # unknown items excluded

    def test_board_columns_match_lifecycle(self):
        """Board columns should match BOARD_COLUMN_ORDER from lifecycle module."""
        assert BOARD_COLUMNS == BOARD_COLUMN_ORDER

    def test_type_aware_epic_refined_idea_goes_to_planning(self):
        """AC-10: project_board passes item_type to status_to_board_bucket."""
        items = [
            self._make_item(1, "refined-idea", item_type="epic"),
            self._make_item(2, "refined-idea", item_type="issue"),
        ]
        board = project_board(items)
        # epic refined-idea -> planning bucket
        assert len(board.columns["planning"]) == 1
        assert board.columns["planning"][0]["id"] == 1
        # issue refined-idea -> refined bucket
        assert len(board.columns["refined"]) == 1
        assert board.columns["refined"][0]["id"] == 2

    def test_type_aware_epic_planning_goes_to_planning(self):
        """Epic with planning status goes to planning bucket."""
        items = [
            self._make_item(1, "planning", item_type="epic"),
        ]
        board = project_board(items)
        assert len(board.columns["planning"]) == 1

    def test_type_aware_epic_reviewing_impl_goes_to_implementing(self):
        """AC-10: epic reviewing-implementation -> implementing, issue -> reviewing."""
        items = [
            self._make_item(1, "reviewing-implementation", item_type="epic"),
            self._make_item(2, "reviewing-implementation", item_type="issue"),
        ]
        board = project_board(items)
        assert len(board.columns["implementing"]) == 1
        assert board.columns["implementing"][0]["id"] == 1
        assert len(board.columns["reviewing"]) == 1
        assert board.columns["reviewing"][0]["id"] == 2


class TestBoardEdgeCases:
    """Edge-case tests for board projection."""

    def test_all_items_frozen(self):
        items = [
            ItemForBoard(item={"id": i}, status="implementing", frozen_value=1)
            for i in range(5)
        ]
        board = project_board(items)
        assert board.stats.total == 0
        for col in BOARD_COLUMNS:
            assert board.columns[col] == []

    def test_mixed_frozen_and_normal(self):
        items = [
            ItemForBoard(item={"id": 1}, status="implementing", frozen_value=0),
            ItemForBoard(item={"id": 2}, status="implementing", frozen_value=1),
            ItemForBoard(item={"id": 3}, status="done", frozen_value=1),
        ]
        board = project_board(items)
        # id=1: implementing (not frozen) -> implementing column
        # id=2: implementing + frozen -> excluded
        # id=3: done (frozen bypass) -> done column
        assert len(board.columns["implementing"]) == 1
        assert len(board.columns["done"]) == 1
        assert board.stats.total == 2

    def test_large_board_stats(self):
        """Verify stats remain correct with many items."""
        items = (
            [ItemForBoard(item={"id": i}, status="done") for i in range(50)]
            + [ItemForBoard(item={"id": i + 50}, status="implementing") for i in range(30)]
            + [ItemForBoard(item={"id": i + 80}, status="idea") for i in range(20)]
        )
        board = project_board(items)
        assert board.stats.total == 100
        assert board.stats.done == 50
        assert board.stats.active == 30
        assert board.stats.remaining == 20
