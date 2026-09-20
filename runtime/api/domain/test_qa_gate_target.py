"""Target parsing and display coverage for QA gates."""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.qa_gate_definitions import independent_item_obligation
from yoke_core.domain.qa_gates import GateTarget

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestGateTarget:
    def test_parse_item(self):
        with patch(
            "yoke_core.domain.yok_n_parser.parse_item_argument",
            return_value=142,
        ):
            target = GateTarget.parse("42")
        assert target.item_id == 142
        assert target.epic_id is None

    def test_parse_epic_task(self):
        with patch(
            "yoke_core.domain.yok_n_parser.parse_item_argument",
            return_value=1833,
        ):
            target = GateTarget.parse("833:5")
        assert target.item_id is None
        assert target.epic_id == 1833
        assert target.task_num == 5

    def test_where_clause_item(self):
        target = GateTarget(item_id=42)
        sql, params = target.where_clause()
        assert "item_id" in sql
        assert "deployment_member_item_id" in sql
        assert "deployment_run_id" not in sql
        assert params == (42, 42)

    def test_admitted_copy_is_not_an_independent_obligation(self):
        assert not independent_item_obligation(
            {"plan_case_key": "admitted-requirement-9"}
        )
        assert independent_item_obligation({"plan_case_key": "flow-case"})
        assert independent_item_obligation({})
        from yoke_core.domain.deployment_qa_stage_prerequisites import (
            DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
        )

        assert not independent_item_obligation(
            {"qa_kind": DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND}
        )

    def test_where_clause_epic(self):
        target = GateTarget(epic_id=833, task_num=5)
        sql, params = target.where_clause()
        assert "epic_id" in sql
        assert params == (833, 5)

    def test_display_name_item(self, monkeypatch):
        # The name is read from the connection the gate itself reads, never
        # an ambient one — a gate runs against a caller-supplied database.
        monkeypatch.setattr(
            "yoke_core.domain.project_identity.render_item_ref",
            lambda conn, item_id: f"YOK-{item_id}",
        )
        conn = object()
        assert GateTarget(item_id=TEST_ITEM_ID).display_name(conn) == TEST_ITEM_REF

    def test_display_name_epic(self, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.project_identity.render_item_ref",
            lambda conn, item_id: f"YOK-{item_id}",
        )
        conn = object()
        assert (
            GateTarget(epic_id=833, task_num=5).display_name(conn)
            == "YOK-833/task 5"
        )
