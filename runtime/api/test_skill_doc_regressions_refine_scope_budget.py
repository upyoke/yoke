"""Refine adds every in-scope budget row itself and escalates only on scope."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read

from yoke_core.domain.idea_readiness_scope_budget import (
    SCOPED_PATH_NOT_IN_FILE_BUDGET,
)


def test_update_protocol_has_no_one_row_limit() -> None:
    text = " ".join(_read(SKILLS / "refine" / "update-protocol.md").split())

    assert "One verified missing owner" not in text
    assert "more than one" not in text
    assert "Any file within the spec's scope that lacks a budget row" in text
    assert "Escalate only when scope changes." in text


def test_readiness_repair_routes_scoped_budget_gaps_into_refine() -> None:
    text = _read(SKILLS / "refine" / "readiness-repair.md")

    assert SCOPED_PATH_NOT_IN_FILE_BUDGET in text
