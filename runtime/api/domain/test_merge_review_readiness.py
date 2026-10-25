"""Landing a standalone branch requires, or enters, the declared review stage."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import merge_review_readiness as readiness
from yoke_core.api import service_client_structured_api_adapter as api
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


def test_one_edge_before_review_is_entered_by_the_merge(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    result = readiness.review_readiness(
        _item(workflow_id="dash", status="implementing"),
        public_ref="ITEM-41",
    )

    assert result.refusal == ""
    assert result.enters_review
    assert (result.source_stage, result.review_stage) == (
        "implementing",
        "reviewing-implementation",
    )
    assert result.review_gates == (
        "db_claim_prose",
        "db_mutation",
        "architecture_impact",
    )


def test_further_back_is_refused_and_names_the_walk(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    result = readiness.review_readiness(
        _item(workflow_id="dash", status="idea"), public_ref="ITEM-41"
    )

    assert not result.enters_review
    assert "'reviewing-implementation', more than one declared edge away" in (
        result.refusal
    )
    assert "--skip-status does not waive review" in result.refusal
    assert "yoke lifecycle transition ITEM-41 --from idea" in result.refusal


def test_the_review_stage_and_beyond_are_admitted(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    for status in ("reviewing-implementation", "done"):
        result = readiness.review_readiness(
            _item(workflow_id="dash", status=status), public_ref="ITEM-41"
        )
        assert result == readiness.ReviewReadiness()


def test_a_workflow_that_declares_no_review_stage_is_admitted(monkeypatch) -> None:
    _serve(monkeypatch, "task")

    result = readiness.review_readiness(
        _item(workflow_id="task", status="implementing"), public_ref="ITEM-41"
    )

    assert result == readiness.ReviewReadiness()


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

    result = readiness.review_readiness(
        _item(workflow_id="dash", status="reviewing-implementation"),
        public_ref="ITEM-41",
    )

    assert "review readiness could not be checked" in result.refusal
    assert "relay unavailable" in result.refusal


def _entry() -> readiness.ReviewReadiness:
    return readiness.ReviewReadiness(
        source_stage="implementing", review_stage="reviewing-implementation"
    )


def test_entering_review_runs_the_declared_transition(monkeypatch) -> None:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, error=None, result={})

    monkeypatch.setattr(api, "call_dispatcher", _dispatch)

    assert readiness.enter_review_stage("ITEM-41", _entry(), reason="green CI") == ""
    assert calls[0]["function_id"] == "lifecycle.transition.execute"
    assert calls[0]["payload"] == {
        "source_status": "implementing",
        "target_status": "reviewing-implementation",
        "reason": "green CI",
    }


def test_a_refused_review_gate_stops_the_merge_with_its_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        api,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(
            success=False,
            result=None,
            error=SimpleNamespace(message="db_claim_prose gate unmet"),
        ),
    )

    refusal = readiness.enter_review_stage("ITEM-41", _entry(), reason="green")

    assert "from 'implementing' to 'reviewing-implementation'" in refusal
    assert "nothing landed: db_claim_prose gate unmet" in refusal


def _gated_entry(*gates: str) -> readiness.ReviewReadiness:
    return readiness.ReviewReadiness(
        source_stage="implementing",
        review_stage="reviewing-implementation",
        review_gates=gates,
    )


def _prose_answer(monkeypatch, response) -> list[dict]:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(readiness, "call_dispatcher", _dispatch)
    return calls


def test_a_prose_mismatch_is_the_review_gate_refusal(monkeypatch) -> None:
    calls = _prose_answer(
        monkeypatch,
        SimpleNamespace(
            success=True,
            error=None,
            result={
                "blocks": True,
                "triggers": ["ALTER TABLE"],
                "recovery": "Amend the DB claim.",
            },
        ),
    )

    refusal = readiness.review_entry_refusal(
        "ITEM-41", _gated_entry("db_claim_prose", "db_mutation")
    )

    assert calls[0]["function_id"] == "db_claim.prose_check"
    assert calls[0]["payload"] == {}
    assert refusal == (
        "entering 'reviewing-implementation' would refuse "
        "GATE_DB_CLAIM_PROSE_MISMATCH: prose-vs-claim mismatch on ITEM-41: "
        "stored db_mutation_profile is state='none' but spec/body declares "
        "governed DB work ('ALTER TABLE').  Amend the DB claim."
    )


def test_clean_prose_passes_and_leaves_the_other_gates_to_the_merge(
    monkeypatch,
) -> None:
    _prose_answer(
        monkeypatch, SimpleNamespace(success=True, error=None, result={"blocks": False})
    )
    entry = _gated_entry("db_claim_prose", "db_mutation", "architecture_impact")

    assert readiness.review_entry_refusal("ITEM-41", entry) == ""
    assert readiness.gates_left_to_merge(entry) == (
        "db_mutation",
        "architecture_impact",
    )


def test_an_unanswered_prose_check_refuses(monkeypatch) -> None:
    _prose_answer(
        monkeypatch,
        SimpleNamespace(
            success=False, result=None, error=SimpleNamespace(message="relay down")
        ),
    )

    refusal = readiness.review_entry_refusal("ITEM-41", _gated_entry("db_claim_prose"))

    assert "read-only check could not be answered: relay down" in refusal
    assert "`yoke db-claim prose-check ITEM-41`" in refusal


def test_a_stage_without_the_prose_gate_asks_nothing(monkeypatch) -> None:
    calls = _prose_answer(monkeypatch, None)

    assert readiness.review_entry_refusal("ITEM-41", _gated_entry("db_mutation")) == ""
    assert calls == []
