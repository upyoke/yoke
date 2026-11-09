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
        "new_migrations_need_db_claim",
        "db_mutation",
        "architecture_impact",
        "path_claim_boundary",
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
        assert result.refusal == ""
        assert not result.enters_review
        assert result.review_gates == ("new_migrations_need_db_claim", "path_claim_boundary")


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
            error=SimpleNamespace(message="db_mutation gate unmet"),
        ),
    )

    refusal = readiness.enter_review_stage("ITEM-41", _entry(), reason="green")

    assert "from 'implementing' to 'reviewing-implementation'" in refusal
    assert "nothing landed: db_mutation gate unmet" in refusal


def _gated_entry(*gates: str) -> readiness.ReviewReadiness:
    return readiness.ReviewReadiness(
        source_stage="implementing",
        review_stage="reviewing-implementation",
        review_gates=gates,
    )


def _review_answer(monkeypatch, response) -> list[dict]:
    calls: list[dict] = []

    def _dispatch(**kwargs):
        calls.append(kwargs)
        return response

    monkeypatch.setattr(readiness, "call_dispatcher", _dispatch)
    return calls


def test_a_stage_without_local_gates_asks_nothing(monkeypatch) -> None:
    calls = _review_answer(monkeypatch, None)

    assert readiness.review_entry_refusal("ITEM-41", _gated_entry("db_mutation")) == ""
    assert calls == []


def test_commit_added_after_review_is_refused_before_landing(monkeypatch, tmp_path):
    import subprocess

    lane = tmp_path / "lane"
    lane.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(lane), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (lane / "base").write_text("base")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "work")
    (lane / "covered.py").write_text("covered")
    git("add", ".")
    git("commit", "-m", "covered work")
    item = _item(workflow_id="dash", status="reviewing-implementation")
    claim = {"id": 9, "state": "active", "integration_target": "main",
             "declared_paths": ["covered.py"]}

    def dispatch(**kwargs):
        if kwargs["function_id"] == "workflows.version.get":
            return _version_response("dash")
        if kwargs["function_id"] == "projects.capability_settings.get":
            return SimpleNamespace(success=True, result={})
        assert kwargs["function_id"] == "claims.path.list"
        return SimpleNamespace(success=True, result={"claims": [claim]})

    monkeypatch.setattr(readiness, "call_dispatcher", dispatch)
    from yoke_core.domain import standalone_item_merge_lane
    monkeypatch.setattr(standalone_item_merge_lane, "lane_path", lambda _: str(lane))
    review = readiness.review_readiness(item, public_ref=item["public_ref"])
    assert not review.enters_review
    assert readiness.review_entry_refusal(item["public_ref"], review, item=item) == ""

    (lane / "after_review.py").write_text("uncovered")
    git("add", ".")
    git("commit", "-m", "work after review")
    refusal = readiness.review_entry_refusal(item["public_ref"], review, item=item)
    assert "after_review.py" in refusal
    assert "yoke claims path widen" in refusal
    claim["declared_paths"].append("after_review.py")
    assert readiness.review_entry_refusal(item["public_ref"], review, item=item) == ""


def test_unreadable_claims_refuse_merge_admission(monkeypatch):
    _review_answer(monkeypatch, SimpleNamespace(
        success=False, error=SimpleNamespace(message="offline"),
    ))
    refusal = readiness.review_entry_refusal(
        "ITEM-41", _gated_entry("path_claim_boundary"), item={},
    )
    assert "offline" in refusal
    assert "retry the merge" in refusal
