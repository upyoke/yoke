"""Landing a standalone branch requires the declared review stage."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_core.domain import merge_review_readiness as readiness
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.workflow_registry import definition_digest


def _item(*, workflow_id: str, status: str) -> dict:
    return {
        "id": 41,
        "public_ref": "ITEM-41",
        "status": status,
        "workflow": {"id": workflow_id, "version": 3},
    }


def _version_response(workflow_id: str):
    definition = builtin_workflow_definition(workflow_id)["definition"]
    return SimpleNamespace(
        success=True,
        error=None,
        result={
            "workflow_id": workflow_id,
            "version": 3,
            "version_id": 300,
            "definition": definition,
            "definition_digest": definition_digest(definition),
        },
    )


def _serve(monkeypatch, workflow_id: str) -> None:
    monkeypatch.setattr(
        readiness,
        "call_dispatcher",
        lambda **_kwargs: _version_response(workflow_id),
    )


def test_implementation_is_refused_and_names_the_declared_review_stage(
    monkeypatch,
) -> None:
    _serve(monkeypatch, "dash")

    refusal = readiness.review_readiness_refusal(
        _item(workflow_id="dash", status="implementing"),
        public_ref="ITEM-41",
    )

    assert "'reviewing-implementation'" in refusal
    assert "--skip-status does not waive that" in refusal
    assert "yoke lifecycle transition ITEM-41" in refusal


def test_the_review_stage_and_beyond_are_admitted(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    for status in ("reviewing-implementation", "done"):
        assert (
            readiness.review_readiness_refusal(
                _item(workflow_id="dash", status=status),
                public_ref="ITEM-41",
            )
            == ""
        )


def test_a_workflow_that_declares_no_review_stage_is_admitted(monkeypatch) -> None:
    _serve(monkeypatch, "task")

    assert (
        readiness.review_readiness_refusal(
            _item(workflow_id="task", status="implementing"),
            public_ref="ITEM-41",
        )
        == ""
    )


def test_an_unreadable_definition_refuses_rather_than_lands(monkeypatch) -> None:
    monkeypatch.setattr(
        readiness,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(message="relay unavailable"),
        ),
    )

    refusal = readiness.review_readiness_refusal(
        _item(workflow_id="dash", status="reviewing-implementation"),
        public_ref="ITEM-41",
    )

    assert "review readiness could not be checked" in refusal
    assert "relay unavailable" in refusal


def test_the_merge_boundary_stops_before_touching_the_lane(
    monkeypatch,
    capsys,
) -> None:
    _serve(monkeypatch, "dash")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_item",
        lambda *_args, **_kwargs: (
            _item(workflow_id="dash", status="implementing"),
            "",
        ),
    )
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("admission must refuse before the checkout is read")
        ),
    )

    exit_code = merge_cli.run(
        [
            "ITEM-41",
            "--skip-status",
            "--session-id",
            "session-1",
            "--json",
        ]
    )

    assert exit_code == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is False
    assert "reviewing-implementation" in envelope["error"]
