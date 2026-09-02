"""Status-write gates must run, be delisted, or name their own skip.

A gate a definition lists, a catalog describes, or a doc teaches, that does
nothing on the write path is indistinguishable from an enforced one to
every reader — so each case below pins the honest outcome instead.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from yoke_core.domain import approval_status_gate
from yoke_core.domain import backlog_authoritative_status_gate
from yoke_core.domain import backlog_updates_helpers
from yoke_core.domain import path_claims_gate
from yoke_core.domain import workflow_activation_status_gates as activation
from yoke_core.domain import workflow_stage_gate_selection
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog


def _catalog_entry(gate_id: str) -> dict:
    return next(entry for entry in workflow_gate_catalog() if entry["id"] == gate_id)


def test_no_inert_file_line_gate_on_the_status_write_path():
    """The 350-line limit is enforced where a checkout exists, not here."""
    assert not [name for name in backlog_updates_helpers.__all__ if "file_line" in name]
    source = inspect.getsource(backlog_authoritative_status_gate)
    assert "file_line" not in source


def test_hard_blocks_gate_refuses_an_unsatisfied_activation_dependency(
    monkeypatch,
):
    """The gate the implementing stage lists actually reads the edges."""
    monkeypatch.setattr(activation, "_table_exists", lambda conn, table: True)
    monkeypatch.setattr(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        lambda item_id, gate_filter=None, conn=None: (
            ["BLOCKED|YOK-1|implementing|Upstream work|activation|status:done"]
            if gate_filter == activation.ACTIVATION_GATE_POINT
            else []
        ),
    )
    failure = activation.evaluate_check_hard_blocks(
        item_id=7, target_status="implementing", db_path="", conn=object()
    )
    assert failure is not None
    assert failure["error_code"] == "GATE_HARD_BLOCKS_UNSATISFIED"
    assert "YOK-1" in failure["error"]


def test_hard_blocks_gate_passes_with_no_unsatisfied_edge(monkeypatch):
    monkeypatch.setattr(activation, "_table_exists", lambda conn, table: True)
    monkeypatch.setattr(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        lambda item_id, gate_filter=None, conn=None: [],
    )
    assert (
        activation.evaluate_check_hard_blocks(
            item_id=7, target_status="implementing", db_path="", conn=object()
        )
        is None
    )


def test_hard_blocks_gate_names_its_skip_when_there_is_no_registry(monkeypatch):
    """A universe without dependency storage records why the gate was absent."""
    monkeypatch.setattr(activation, "_table_exists", lambda conn, table: False)
    recorded: list[dict] = []
    monkeypatch.setattr(
        activation,
        "record_gate_absence",
        lambda **kwargs: recorded.append(kwargs),
    )
    assert (
        activation.evaluate_check_hard_blocks(
            item_id=7, target_status="implementing", db_path="", conn=object()
        )
        is None
    )
    assert recorded[0]["gate_id"] == "check_hard_blocks"
    assert recorded[0]["reason"] == "dependency_registry_absent"


def test_claim_activation_gate_refuses_a_claim_that_never_locked(monkeypatch):
    monkeypatch.setattr(
        path_claims_gate, "gate_state_for_item", lambda conn, item_id: [(3, "planned")]
    )
    failure = activation.evaluate_claim_activation(
        item_id=7, target_status="implementing", db_path="", conn=object()
    )
    assert failure is not None
    assert failure["error_code"] == "GATE_CLAIM_ACTIVATION_UNSATISFIED"
    assert "id=3 state=planned" in failure["error"]


def test_claim_activation_names_its_skip_when_there_is_no_registry(monkeypatch):
    """An inapplicable gate records the absence rather than passing quietly."""
    monkeypatch.setattr(
        path_claims_gate, "gate_state_for_item", lambda conn, item_id: None
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        activation,
        "record_gate_absence",
        lambda **kwargs: recorded.append(kwargs),
    )
    assert (
        activation.evaluate_claim_activation(
            item_id=7, target_status="implementing", db_path="", conn=object()
        )
        is None
    )
    assert recorded[0]["gate_id"] == "claim_activation"
    assert recorded[0]["reason"] == "path_claim_registry_absent"


def test_optional_path_survey_removes_the_conflict_survey_gate(monkeypatch):
    """The published policy composes the stage list instead of decorating it."""
    gates = ({"id": "conflict_survey"}, {"id": "architecture_impact"})
    monkeypatch.setattr(
        "yoke_core.domain.workflow_effective_policies"
        ".load_item_effective_workflow_policies",
        lambda conn, item_id: SimpleNamespace(requires_path_survey=False),
    )
    selected = workflow_stage_gate_selection.select_stage_gates(
        gates, item_id=7, db_path="", conn=object()
    )
    assert [ref["id"] for ref in selected] == ["architecture_impact"]


def test_required_path_survey_keeps_the_conflict_survey_gate(monkeypatch):
    gates = ({"id": "conflict_survey"}, {"id": "architecture_impact"})
    monkeypatch.setattr(
        "yoke_core.domain.workflow_effective_policies"
        ".load_item_effective_workflow_policies",
        lambda conn, item_id: SimpleNamespace(requires_path_survey=True),
    )
    selected = workflow_stage_gate_selection.select_stage_gates(
        gates, item_id=7, db_path="", conn=object()
    )
    assert [ref["id"] for ref in selected] == [
        "conflict_survey",
        "architecture_impact",
    ]


def test_architecture_catalog_describes_what_the_runner_enforces():
    """One architecture story: the catalog stops promising model conformance."""
    description = _catalog_entry("architecture_impact")["description"]
    assert "must honor the project's" not in description
    assert "uncertain" in description
    assert "Doctor" in description


def test_approval_gate_is_absent_until_an_authority_is_declared(monkeypatch):
    monkeypatch.setattr(
        approval_status_gate,
        "connect",
        lambda db_path: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        approval_status_gate,
        "load_item_workflow_runtime",
        lambda conn, item_id: SimpleNamespace(policies={"approval_defaults": {}}),
    )
    monkeypatch.setattr(
        "yoke_core.domain.dash_posture_gate.approval_policy_for_transition",
        lambda conn, item_id, target_status: None,
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        approval_status_gate,
        "record_gate_absence",
        lambda **kwargs: recorded.append(kwargs),
    )
    assert (
        approval_status_gate.evaluate(item_id=7, target_status="done", db_path="")
        is None
    )
    assert recorded[0]["gate_id"] == "approval"
    assert recorded[0]["reason"] == "approval_authority_undeclared"


def test_approval_gate_matches_the_workflow_policy_source(monkeypatch):
    monkeypatch.setattr(
        approval_status_gate,
        "connect",
        lambda db_path: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        approval_status_gate,
        "load_item_workflow_runtime",
        lambda conn, item_id: SimpleNamespace(
            policies={"approval_defaults": {"done": {"roles": ["owner"]}}}
        ),
    )
    item = {
        "status": "reviewing-implementation",
        "workflow_id": "dash",
        "workflow_version_id": 7,
    }
    context = {
        "from_stage": "reviewing-implementation",
        "to_stage": "done",
        "workflow_id": "dash",
        "workflow_version_id": 7,
        "approval_source": {
            "kind": "workflow_approval_default",
            "entry": "approval_defaults.done",
        },
    }
    monkeypatch.setattr(approval_status_gate, "load_lifecycle_item", lambda *a: item)
    monkeypatch.setattr(
        approval_status_gate,
        "list_subject_requests",
        lambda *a: [
            {
                "id": 17,
                "status": "resolved",
                "resolution_action": "approve",
                "subject_context": context,
                "consumed_at": None,
            }
        ],
    )

    assert (
        approval_status_gate.evaluate(item_id=7, target_status="done", db_path="")
        is None
    )
