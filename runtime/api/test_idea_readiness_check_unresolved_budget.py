"""UNRESOLVED File Budget is accepted at idea; blocked at refine exit."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.file_budget_paths import (
    has_resolved_file_budget,
    has_unresolved_file_budget,
)
from yoke_core.domain.file_budget_required_gate import evaluate as budget_gate
from yoke_core.domain.idea_readiness_check import run_all_checks

_UNRESOLVED_PROSE = (
    "## File Budget\n\n"
    "UNRESOLVED — this work item creates/grows authored code but the "
    "file shape is not yet known. `/yoke refine` MUST resolve the "
    "expected implementation shape before this item advances past "
    "`refining-idea`.\n"
)


class TestUnresolvedFileBudgetDetector:
    def test_prose_unresolved_with_emdash(self):
        spec = (
            "## File Budget\n\n"
            "UNRESOLVED — refine must resolve before refining-idea.\n"
        )
        assert has_unresolved_file_budget(spec) is True
        assert has_resolved_file_budget(spec) is False

    def test_bare_unresolved_token(self):
        assert has_unresolved_file_budget("## File Budget\n\nUNRESOLVED\n") is True

    def test_list_na_unresolved(self):
        spec = "## File Budget\n\n- N/A — unresolved\n"
        assert has_unresolved_file_budget(spec) is True
        assert has_resolved_file_budget(spec) is False

    def test_reasoned_na_is_resolved_not_unresolved(self):
        spec = (
            "## File Budget\n\n"
            "- N/A — docs-only updates to README.\n"
        )
        assert has_resolved_file_budget(spec) is True
        assert has_unresolved_file_budget(spec) is False

    def test_empty_section_is_neither(self):
        assert has_unresolved_file_budget("## File Budget\n") is False
        assert has_resolved_file_budget("## File Budget\n") is False

    def test_path_budget_is_resolved(self):
        spec = "## File Budget\n\n- `runtime/api/domain/foo.py`\n"
        assert has_resolved_file_budget(spec) is True
        assert has_unresolved_file_budget(spec) is False


@pytest.fixture
def required_budget_item(test_db):
    def _insert(*, item_id: int, status: str, spec: str):
        return insert_item(
            test_db,
            id=item_id,
            workflow_id="dash",
            status=status,
            workflow_posture=json.dumps({"file_budget": True}),
            spec=spec,
        )

    return _insert


def test_idea_readiness_accepts_unresolved_file_budget(required_budget_item, test_db):
    required_budget_item(item_id=4101, status="idea", spec=_UNRESOLVED_PROSE)

    # Strict gate stays blocked — advance / migration must not pass.
    assert budget_gate(test_db, 4101)["verdict"] == "block"
    assert [
        issue.code for issue in run_all_checks(test_db, 4101)
    ] == []


def test_refining_idea_readiness_blocks_unresolved_file_budget(
    required_budget_item, test_db,
):
    required_budget_item(
        item_id=4102, status="refining-idea", spec=_UNRESOLVED_PROSE,
    )

    assert budget_gate(test_db, 4102)["verdict"] == "block"
    assert any(
        issue.code == "MISSING_FILE_BUDGET"
        for issue in run_all_checks(test_db, 4102)
    )


def test_idea_readiness_still_blocks_empty_file_budget(
    required_budget_item, test_db,
):
    required_budget_item(
        item_id=4103, status="idea", spec="## File Budget\n",
    )

    assert any(
        issue.code == "MISSING_FILE_BUDGET"
        for issue in run_all_checks(test_db, 4103)
    )
