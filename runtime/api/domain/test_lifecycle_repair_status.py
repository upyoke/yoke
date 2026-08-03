"""Registered lifecycle-repair handler and CLI contract tests."""

from __future__ import annotations

from typing import Any

import pytest

from yoke_cli.commands.adapters import lifecycle_repair as cli
from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.handlers import lifecycle_repair_status as handler
from yoke_core.domain.status_claim_bypass_context import resolve_claim_bypass


class _Workflow:
    workflow_id = "test"
    version = 1
    stage_ids = ("idea", "planned", "done")

    def accepts_stage(self, status: str) -> bool:
        return status in self.stage_ids


def _request(payload: dict[str, Any]) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="lifecycle.repair_status.execute",
        actor=ActorContext(actor_id="7", session_id="operator-session"),
        target=TargetRef(kind="item", item_id=42, project_id="yoke"),
        payload=payload,
    )


def test_dry_run_validates_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handler,
        "_read_item_state",
        lambda _item_id: ("planned", _Workflow()),
    )

    def unexpected_update(**_kwargs):
        raise AssertionError("dry-run must not invoke backlog.execute_update")

    monkeypatch.setattr(backlog, "execute_update", unexpected_update)
    outcome = handler.handle_repair_status(
        _request(
            {
                "target_status": "done",
                "source_status": "planned",
                "reason": "merged evidence reconciled",
                "dry_run": True,
            }
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "item_id": 42,
        "from_status": "planned",
        "to_status": "done",
        "reason": "merged evidence reconciled",
        "dry_run": True,
        "changed": True,
        "log": "",
    }


def test_apply_uses_request_scoped_claim_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handler,
        "_read_item_state",
        lambda _item_id: ("planned", _Workflow()),
    )
    captured: dict[str, Any] = {}

    def execute_update(**kwargs):
        captured.update(kwargs)
        captured["bypass"] = resolve_claim_bypass()
        return {"success": True}

    monkeypatch.setattr(backlog, "execute_update", execute_update)
    outcome = handler.handle_repair_status(
        _request(
            {
                "target_status": "done",
                "reason": "merged evidence reconciled",
            }
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["changed"] is True
    assert captured["done_nonce_verified"] is True
    assert captured["qa_bypass"] is False
    assert captured["expected_status"] == "planned"
    assert captured["session_id"] == "operator-session"
    assert captured["bypass"] == (
        "repair-status:merged evidence reconciled",
        "repair-status:merged evidence reconciled",
    )
    assert resolve_claim_bypass() == ("", "")


def test_invalid_stage_and_stale_source_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handler,
        "_read_item_state",
        lambda _item_id: ("planned", _Workflow()),
    )
    stale = handler.handle_repair_status(
        _request(
            {
                "target_status": "done",
                "source_status": "idea",
                "reason": "reconcile",
            }
        )
    )
    invalid = handler.handle_repair_status(
        _request(
            {
                "target_status": "not-a-stage",
                "reason": "reconcile",
            }
        )
    )

    assert stale.primary_success is False
    assert stale.error is not None
    assert stale.error.code == "precondition_failed"
    assert invalid.primary_success is False
    assert invalid.error is not None
    assert invalid.error.code == "validation_error"


def test_whitespace_reason_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handler,
        "_read_item_state",
        lambda _item_id: ("planned", _Workflow()),
    )
    outcome = handler.handle_repair_status(
        _request({"target_status": "done", "reason": "   "})
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "invalid_payload"


def test_registration_requires_operator_override() -> None:
    registration = handler.REGISTRATIONS[0]
    assert registration["function_id"] == "lifecycle.repair_status.execute"
    assert registration["claim_required_kind"] == "operator_override"
    assert "operator_reason_required" in registration["guardrails"]


def test_registration_and_cli_inventory_are_complete() -> None:
    from yoke_core.domain import yoke_function_registry
    from yoke_core.domain.handlers import __init_register__

    yoke_function_registry.reset_registry_for_tests()
    try:
        __init_register__.register_all_handlers()
        entry = yoke_function_registry.lookup("lifecycle.repair_status.execute")
        assert entry is not None
        assert entry.claim_required_kind == "operator_override"
    finally:
        yoke_function_registry.reset_registry_for_tests()

    function_id, adapter = SUBCOMMAND_REGISTRY[("lifecycle", "repair-status")]
    assert function_id == "lifecycle.repair_status.execute"
    assert adapter is cli.lifecycle_repair_status
    assert "yoke lifecycle repair-status" in ADAPTER_USAGE[function_id]

    authz = classify(
        function_id,
        side_effects=True,
        project_permission=PERM_ITEMS_WRITE,
    )
    assert authz.scope == PROJECT
    assert authz.permission_key == PERM_ITEMS_WRITE


def test_cli_dispatches_transport_keyed_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def dispatch_and_emit(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "dispatch_and_emit", dispatch_and_emit)
    rc = cli.lifecycle_repair_status(
        [
            "YOK-42",
            "--from",
            "planned",
            "--to",
            "done",
            "--reason",
            "merged evidence reconciled",
            "--dry-run",
            "--session-id",
            "operator-session",
        ]
    )

    assert rc == 0
    assert captured["function_id"] == "lifecycle.repair_status.execute"
    assert captured["target"].item_ref == "YOK-42"
    assert captured["payload"] == {
        "target_status": "done",
        "source_status": "planned",
        "reason": "merged evidence reconciled",
        "dry_run": True,
    }
    assert captured["session_id"] == "operator-session"
