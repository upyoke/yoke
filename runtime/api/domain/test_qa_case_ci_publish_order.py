"""The CI case rebases before its single lane publication and dispatch."""

from __future__ import annotations

from unittest import mock

from runtime.api.domain.qa_case_ci_test_helpers import ci_case, wire_ci_case
from yoke_core.domain import (
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_ci_run,
)


def test_live_dispatch_rebases_then_pushes_and_dispatches_once(
    tmp_path,
    monkeypatch,
):
    checkout, _, _ = wire_ci_case(tmp_path, monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        qa_case_ci_entry_run,
        "prepare_ci_lane",
        lambda *a, **k: order.append("rebase"),
    )
    monkeypatch.setattr(
        qa_case_ci_lane,
        "push_lane",
        lambda *a, **k: order.append("push"),
    )
    dispatch = mock.Mock(side_effect=lambda **k: order.append("dispatch") or "42")
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "await_workflow",
        lambda **k: (0, "success"),
    )

    qa_case_ci_run.execute_ci_case(ci_case(), checkout_path=checkout)

    assert order == ["rebase", "push", "dispatch"]
    dispatch.assert_called_once()
