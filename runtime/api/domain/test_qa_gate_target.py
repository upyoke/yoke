"""Target parsing and display coverage for QA gates."""

from __future__ import annotations

from yoke_core.domain.qa_gates import GateTarget

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestGateTarget:
    def test_parse_item(self):
        target = GateTarget.parse("42")
        assert target.item_id == 42
        assert target.epic_id is None

    def test_parse_epic_task(self):
        target = GateTarget.parse("833:5")
        assert target.item_id is None
        assert target.epic_id == 833
        assert target.task_num == 5

    def test_where_clause_item(self):
        target = GateTarget.parse("42")
        sql, params = target.where_clause()
        assert "item_id" in sql
        assert params == (42,)

    def test_where_clause_epic(self):
        target = GateTarget.parse("833:5")
        sql, params = target.where_clause()
        assert "epic_id" in sql
        assert params == (833, 5)

    def test_display_name_item(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.project_identity_item_ref.item_ref_for_id",
            lambda item_id: f"YOK-{item_id}",
        )
        assert GateTarget.parse(str(TEST_ITEM_ID)).display_name() == TEST_ITEM_REF

    def test_display_name_epic(self):
        assert GateTarget.parse("833:5").display_name() == "epic 833/task 5"
