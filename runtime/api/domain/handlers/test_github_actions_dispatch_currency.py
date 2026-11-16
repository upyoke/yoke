"""A deploy stage dispatch is current only while no newer intent replaced it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.github_workflow_dispatch_intents import (
    claim_attempt,
    deploy_stage_scope,
)
from yoke_core.domain.handlers import github_actions_dispatch_currency as subject
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

STAGE = "deploy:yoke:run-20261116-002:release"


def _claim(request_id: str, correlation_id: str, *, scope: str = "project:7") -> None:
    assert claim_attempt(
        request_id=request_id,
        attempt=1,
        actor_id="2",
        authorization_scope=scope,
        payload_checksum=f"checksum-{correlation_id}",
        repo="upyoke/yoke",
        workflow="platform-release-bridge.yml",
        workflow_ref="main",
        inputs={"yoke_dispatch_id": correlation_id},
        correlation_id=correlation_id,
    )


def _age(db_path, correlation_id: str, minutes: int, state: str = "completed") -> None:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with connect_test_db(db_path) as conn:
        conn.execute(
            "UPDATE github_workflow_dispatch_intents SET created_at=%s, state=%s "
            "WHERE correlation_id=%s",
            (stamp, state, correlation_id),
        )
        conn.commit()


@pytest.fixture
def ask(monkeypatch):
    monkeypatch.setattr(
        subject,
        "_validate_and_resolve_auth",
        lambda req, model, function_id, **_: (
            model.model_validate(req.payload),
            object(),
            None,
        ),
    )

    def _ask(correlation_id: str, authorized=7):
        return subject.handle_dispatch_currency_get(
            FunctionCallRequest(
                function=subject.FUNCTION_ID,
                actor=ActorContext(actor_id="1", session_id="currency-test"),
                target=TargetRef(kind="global"),
                payload={"project": "yoke", "correlation_id": correlation_id},
                options={"authorized_project_id": authorized},
            )
        )

    return _ask


def test_scope_is_the_deploy_stage_prefix_of_every_retrigger() -> None:
    assert deploy_stage_scope(STAGE) == STAGE
    assert deploy_stage_scope(f"{STAGE}:fresh:abc") == STAGE
    assert deploy_stage_scope(f"{STAGE}:stale:99") == STAGE
    assert deploy_stage_scope("content-key") == ""
    assert deploy_stage_scope("deploy:yoke::release") == ""


def test_fresh_redrive_supersedes_the_stuck_dispatch(tmp_path: Path, ask) -> None:
    with init_test_db(tmp_path) as db_path:
        _claim(STAGE, "stuck")
        _claim(f"{STAGE}:fresh:abc", "replacement")
        # A neighbouring stage and a longer stage name sharing a prefix
        # are other scopes; they never supersede this one.
        _claim("deploy:yoke:run-20261116-002:release-qa", "other-stage")
        _claim("deploy:yoke:run-20261116-002:releasex:fresh:1", "lookalike")
        _age(db_path, "stuck", 30)
        _age(db_path, "replacement", 5)

        stuck = ask("stuck").result_payload
        replacement = ask("replacement").result_payload

    assert stuck["found"] and stuck["current"] is False
    assert stuck["scope"] == STAGE
    assert stuck["newest_correlation_id"] == "replacement"
    assert replacement["current"] is True


def test_a_rejected_newer_post_replaces_nothing(tmp_path: Path, ask) -> None:
    with init_test_db(tmp_path) as db_path:
        _claim(STAGE, "original")
        _claim(f"{STAGE}:fresh:abc", "rejected")
        _age(db_path, "original", 30)
        _age(db_path, "rejected", 5, state="rejected")

        assert ask("original").result_payload["current"] is True


def test_unknown_foreign_and_non_deploy_dispatches(tmp_path: Path, ask) -> None:
    with init_test_db(tmp_path):
        _claim(STAGE, "foreign", scope="project:8")
        _claim("content-key", "content")

        assert ask("missing").result_payload == {
            "found": False,
            "current": False,
            "scope": "",
            "newest_correlation_id": "",
            "newest_run_id": "",
        }
        foreign = ask("foreign")
        assert foreign.error.code == "workflow_dispatch_scope_mismatch"
        assert foreign.result_payload == {}
        content = ask("content")
        assert content.error.code == "workflow_dispatch_not_deploy_stage"


def test_currency_cli_routes_the_correlation_and_project(monkeypatch, capsys):
    from yoke_cli.commands.adapters import github_actions_dispatch_receipt as adapter
    from yoke_cli.main import main
    from yoke_contracts.api.function_call import FunctionCallResponse

    seen = []

    def call(function_id, payload, **kwargs):
        seen.append((function_id, payload))
        return FunctionCallResponse(
            success=True,
            function=function_id,
            version="v1",
            result={"found": True, "current": False},
        )

    monkeypatch.setattr(adapter, "_call", call)
    argv = ["github-actions", "dispatch-intent", "current", "stuck"]
    assert main([*argv, "--project", "yoke", "--json"]) == 0
    assert seen == [(subject.FUNCTION_ID, {"project": "yoke", "correlation_id": "stuck"})]
    assert '"current": false' in capsys.readouterr().out
