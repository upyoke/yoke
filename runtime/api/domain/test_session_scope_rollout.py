"""Mixed client, server and schema registration compatibility."""

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.api.domain.test_session_registration_scope import world  # noqa: F401
from yoke_cli.transport.function_version_skew import retype_skew
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain import schema_readiness
from yoke_core.domain.migration_yoke_ledger import YOKE_LEDGER_CONTRACT
from yoke_core.domain.sessions_identity_read import SessionIdentity
from yoke_cli.commands.adapters import sessions as adapter


def test_legacy_begin_renders_named_scope_refusal(monkeypatch, capsys):
    from yoke_core.hooks import sessions_cli
    from yoke_core.domain.sessions_analytics import SessionError

    def refused(*args, **kwargs):
        raise SessionError(
            "SESSION_ORG_MEMBERSHIP_REQUIRED",
            "Recovery: reconnect to your organization.",
        )

    monkeypatch.setattr(
        sessions_cli, "connect", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(sessions_cli, "cmd_begin", refused)
    monkeypatch.setattr(
        "yoke_contracts.project_defaults.default_project_for_directory",
        lambda path: None,
    )
    with pytest.raises(SystemExit) as stopped:
        sessions_cli.main(["begin", "session", "codex", "test", "", "/tmp/unmapped"])
    assert stopped.value.code == 1
    assert "SESSION_ORG_MEMBERSHIP_REQUIRED: Recovery:" in capsys.readouterr().err


@pytest.mark.parametrize("project", [None, 1])
@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_public_begin_dispatches_exclusive_scope(monkeypatch, project, executor):
    calls = []
    monkeypatch.setattr(adapter, "uncorroborated_reason", lambda sid: None)
    monkeypatch.setattr(
        adapter, "_resolve_begin_project_id", lambda explicit, workspace: project
    )
    monkeypatch.setattr(
        adapter, "dispatch_and_emit", lambda **kw: calls.append(kw) or 0
    )
    assert (
        adapter.sessions_begin(
            [
                "--executor",
                executor,
                "--provider",
                "test",
                "--requested-model",
                "test",
                "--workspace",
                "/tmp/unmapped",
                "--session-id",
                "corroborated",
            ]
        )
        == 0
    )
    assert calls[0]["function_id"] == "sessions.begin"
    assert calls[0]["payload"]["project_id"] == project
    assert calls[0]["payload"].get("machine_scope", False) == (project is None)


@pytest.mark.parametrize("explicit", ["bogus", "0", "-1"])
def test_public_begin_refuses_explicit_invalid_project(monkeypatch, explicit):
    monkeypatch.setattr(adapter, "uncorroborated_reason", lambda sid: None)
    monkeypatch.setattr(
        adapter,
        "dispatch_and_emit",
        lambda **kw: pytest.fail("invalid input dispatched"),
    )
    assert (
        adapter.sessions_begin(
            [
                "--executor",
                "codex",
                "--provider",
                "test",
                "--requested-model",
                "test",
                "--workspace",
                "/tmp/unmapped",
                "--project",
                explicit,
            ]
        )
        == 2
    )


def test_public_begin_preserves_identity_guard(monkeypatch):
    monkeypatch.setattr(
        adapter, "uncorroborated_reason", lambda sid: "identity uncorroborated"
    )
    monkeypatch.setattr(
        adapter,
        "dispatch_and_emit",
        lambda **kw: pytest.fail("foreign identity dispatched"),
    )
    assert (
        adapter.sessions_begin(
            [
                "--executor",
                "codex",
                "--provider",
                "test",
                "--requested-model",
                "test",
                "--workspace",
                "/tmp/unmapped",
            ]
        )
        == 2
    )


def test_new_client_old_server_argument_floor_refusal():
    request = FunctionCallRequest(
        function="sessions.begin",
        actor=ActorContext(session_id="new-client"),
        target=TargetRef(kind="global"),
        payload={"project_id": None, "machine_scope": True},
    )
    response = FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code="payload_invalid", message="extra argument machine_scope"
        ),
    )
    reply = retype_skew(response, request, server_version="0.1.0", env_name="prod")
    assert reply.error.code == "function_argument_version_skew"
    assert (
        "machine_scope" in reply.error.message and "next-release" in reply.error.message
    )
    assert (
        "start the agent inside a registered project folder"
        in reply.error.recovery_hint
    )
    assert not reply.success


def test_old_client_new_server_project_registration(world):  # noqa: F811
    sid = str(uuid4())
    result = begin_session(
        world.conn,
        session_id=sid,
        executor="codex",
        provider="test",
        model_facts=SessionModelFacts(),
        workspace="/tmp/project",
        project_id=1,
        actor_id=world.owner,
        machine_id=str(uuid4()),
    )
    assert result["success"]
    row = world.conn.execute(
        "SELECT project_id, org_id, actor_id FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone()
    assert tuple(row) == (1, None, world.owner)


def test_old_build_refuses_converged_db():
    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            "CREATE TABLE applied_migrations (migration_name TEXT PRIMARY KEY, "
            "applied_at TEXT, applied_by TEXT, minimum_serving_version TEXT)"
        )
        conn.execute(
            "INSERT INTO applied_migrations VALUES (?, 'now', 'test', '2.0.0')",
            ("0078_project_optional_sessions",),
        )
        findings = schema_readiness.stranded_by_applied_migrations(
            conn,
            "1.0.0",
            (),
            YOKE_LEDGER_CONTRACT,
        )
        assert len(findings) == 1
        assert "0078_project_optional_sessions" in findings[0]
        assert "2.0.0" in findings[0] and "1.0.0" in findings[0]


def test_identity_read_tolerates_absent_org_field():
    identity = SessionIdentity(
        session_id="old-client",
        executor="codex",
        executor_surface=None,
        executor_version=None,
        machine_id=None,
        provider="test",
        model="",
        requested_model="",
        workspace="/tmp/project",
        execution_level="primary",
        project_id=1,
    )
    assert identity.org_id is None and identity.scope_kind == "project"


@pytest.mark.parametrize("effort", ["medium", "INVALID"])
def test_legacy_begin_validates_explicit_effort(test_db, effort):
    registration = test_db
    from yoke_core.hooks.sessions_lifecycle import cmd_begin

    sid = str(uuid4())
    if effort == "INVALID":
        with pytest.raises(ValueError, match="reasoning effort"):
            cmd_begin(
                registration,
                sid,
                "codex",
                "test",
                "",
                "/tmp/unmapped",
                project_id=None,
                reasoning_effort=effort,
            )
        assert (
            registration.execute(
                "SELECT 1 FROM harness_sessions WHERE session_id=%s", (sid,)
            ).fetchone()
            is None
        )
    else:
        cmd_begin(
            registration,
            sid,
            "codex",
            "test",
            "",
            "/tmp/unmapped",
            project_id=None,
            reasoning_effort=effort,
        )
        assert (
            registration.execute(
                "SELECT reasoning_effort FROM harness_sessions WHERE session_id=%s",
                (sid,),
            ).fetchone()[0]
            == effort
        )
