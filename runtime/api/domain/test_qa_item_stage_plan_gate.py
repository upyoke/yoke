"""An item whose flow asks it to prove itself must bring its own plan.

Both halves matter: the flow has to actually declare an item-scoped QA
stage, and only then is a missing plan worth refusing a landing over. A
flow with no such stage — which is most flows, in most projects — is
untouched.

The gate runs client-side, inside the merge engine, so it reads both halves
from what the serving control plane already hands it: the flow's stages
through a relayed read, and the attachments on the item payload the merge
already holds. These exercise it at that seam.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    item_qa_stage_definitions,
)
from yoke_core.domain import qa_item_stage_plan_gate as gate

PUBLIC_REF = "YOK-1927"
ITEM_SCOPED_STAGES = item_qa_stage_definitions(None, environment="development")


def _run_scoped_stages() -> list[dict]:
    """A flow whose only QA stage answers for the whole run, not per item."""
    stages = item_qa_stage_definitions(None, environment="development")
    stages[1]["scope"] = "run"
    return stages


def _item(
    *,
    flow_id: str = "flow-item-scoped",
    attachments: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "deployment_flow": flow_id,
        "project": {"slug": "yoke"},
        "qa_plan_attachments": attachments or [],
        "workflow": {"id": "dash", "version": 9, "version_id": 663},
    }


def _refusal(
    monkeypatch,
    item: dict,
    stages: Any,
    error: str = "",
    transition: str = "release",
) -> str:
    monkeypatch.setattr(gate, "flow_stages", lambda flow_id: (stages, error))
    monkeypatch.setattr(gate, "attachment_transition", lambda _item: transition)
    return gate.missing_item_qa_plan_refusal(item, public_ref=PUBLIC_REF)


def test_item_scoped_qa_stage_is_recognised() -> None:
    assert gate.stages_declare_item_scoped_qa(ITEM_SCOPED_STAGES) is True
    # The serving read hands stages back as a JSON string.
    assert gate.stages_declare_item_scoped_qa(json.dumps(ITEM_SCOPED_STAGES)) is True
    assert gate.stages_declare_item_scoped_qa(_run_scoped_stages()) is False
    assert gate.stages_declare_item_scoped_qa("") is False
    assert gate.stages_declare_item_scoped_qa("not json") is False


def test_landing_is_refused_without_an_attached_plan(monkeypatch) -> None:
    refusal = _refusal(monkeypatch, _item(), ITEM_SCOPED_STAGES)
    assert refusal
    # The refusal has to be actionable on its own: what is wrong, and the
    # attach-then-dry-run recipe that fixes it.
    assert "item-scoped QA stage" in refusal
    assert f"yoke qa item-plan attach --item {PUBLIC_REF}" in refusal
    assert "--qa-phase post_deploy" in refusal
    assert f"yoke qa plan run --item {PUBLIC_REF}" in refusal
    # The recipe has to name the transition the attach command accepts
    # for a post-deploy binding, or it recommends its own refusal.
    assert "--transition release" in refusal


def test_an_attached_post_deploy_plan_clears_the_landing(monkeypatch) -> None:
    item = _item(
        attachments=[{"plan_id": 7, "qa_phase": "post_deploy"}],
    )
    assert _refusal(monkeypatch, item, ITEM_SCOPED_STAGES) == ""


def test_a_verification_attachment_does_not_answer_for_the_deployment(
    monkeypatch,
) -> None:
    item = _item(attachments=[{"plan_id": 7, "qa_phase": "verification"}])
    assert _refusal(monkeypatch, item, ITEM_SCOPED_STAGES) != ""


def test_a_flow_without_an_item_scoped_stage_never_asks(monkeypatch) -> None:
    assert _refusal(monkeypatch, _item(), _run_scoped_stages()) == ""


def test_an_item_with_no_flow_is_unaffected(monkeypatch) -> None:
    assert _refusal(monkeypatch, _item(flow_id=""), ITEM_SCOPED_STAGES) == ""


def test_the_attach_transition_comes_from_the_pinned_workflow(
    monkeypatch,
) -> None:
    """A workflow with no delivery wait binds post-deploy acceptance at done."""

    def _version(function_id: str, payload: dict) -> tuple[Any, str]:
        assert function_id == "workflows.version.get"
        return {
            "definition": {
                "stages": [{"id": "implementing"}, {"id": "done"}],
                "terminal_stage_ids": ["done"],
                "policies": {"delivery": "none"},
                "transitions": [
                    {"from_stage_id": "implementing", "to_stage_id": "done"}
                ],
            }
        }, ""

    monkeypatch.setattr(gate, "_relay", _version)
    assert gate.attachment_transition(_item()) == "done"


def test_an_unreadable_workflow_falls_back_to_the_terminal_stage(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        gate, "_relay", lambda function_id, payload: (None, "relay down")
    )
    assert gate.attachment_transition(_item()) == gate.DEFAULT_ATTACHMENT_TRANSITION
    assert gate.attachment_transition({}) == gate.DEFAULT_ATTACHMENT_TRANSITION


def test_an_unreadable_flow_refuses_rather_than_clearing(monkeypatch) -> None:
    refusal = _refusal(
        monkeypatch, _item(), None, error="deployment_flows.stages read failed"
    )
    assert "read failed" in refusal
