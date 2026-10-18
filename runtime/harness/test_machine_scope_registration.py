"""Projectless registration and relay compatibility across native harnesses."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.api.fixtures.backlog import test_db  # noqa: F401
from runtime.api.cli.test_yoke_operations_cli_hooks import _FakeResponse
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.hook_evaluator_protocol import (
    HOOK_EVALUATOR_CAPABILITIES,
    HOOK_MACHINE_SCOPE_CAPABILITY,
)
from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_contracts.session_model_facts import SessionModelFacts
from yoke_core.domain import db_helpers
from yoke_core.hooks import registration_in_process, session_lifecycle_client
from yoke_harness.hooks import identity_relay, relay
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation


@pytest.fixture(params=["claude", "codex", "cursor"])
def harness(request):
    root = Path(__file__).resolve().parents[2]
    return json.loads(
        (root / ".yoke/harness" / request.param / "manifest.json").read_text()
    )["harness_id"]


@pytest.fixture
def registration(test_db, monkeypatch):  # noqa: F811
    class BorrowedConnection:
        def __getattr__(self, name):
            return getattr(test_db, name)

        def close(self):
            pass

    monkeypatch.setattr(db_helpers, "connect", BorrowedConnection)
    return test_db


@pytest.mark.parametrize("project", [None, 1])
def test_outside_project_registers_machine_scope_in_process(
    registration, harness, project
):
    sid = f"registration-{uuid4()}"
    assert (
        registration_in_process._register_in_process(
            sid,
            harness,
            "test",
            SessionModelFacts(),
            "/tmp/unmapped",
            None,
            project_id=project,
            machine_id=str(uuid4()),
        )
        == ""
    )
    row = registration.execute(
        "SELECT project_id, org_id, actor_id, executor FROM harness_sessions "
        "WHERE session_id=%s",
        (sid,),
    ).fetchone()
    assert row[0] == project and row[2] is not None and row[3] == harness
    assert (row[1] is not None) == (project is None)


@pytest.mark.parametrize("project", [None, 1])
def test_inside_project_registers_project_scope(monkeypatch, harness, project):
    calls = []
    monkeypatch.setattr(
        session_lifecycle_client, "_relay_owns_registration", lambda: False
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_local_authority_active", lambda: True
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_project_id_for_root", lambda root: project
    )
    monkeypatch.setattr(
        "yoke_core.hooks.registration._register_in_process",
        lambda *a, **kw: calls.append(kw) or "",
    )
    assert (
        session_lifecycle_client.register_harness_session(
            root="/tmp/workspace",
            session_id="client",
            executor=harness,
            provider="test",
            model_facts=SessionModelFacts(),
            native_thread_id="native",
        )
        == ""
    )
    assert calls[0]["project_id"] == project
    assert calls[0]["machine_scope"] == (project is None)


def test_reinstall_keeps_scope(registration, harness):
    sid, machine = str(uuid4()), str(uuid4())
    for project in [None, 1, None]:
        assert (
            registration_in_process._register_in_process(
                sid,
                harness,
                "test",
                SessionModelFacts(),
                "/tmp/reinstalled",
                None,
                project_id=project,
                machine_id=machine,
            )
            == ""
        )
        row = registration.execute(
            "SELECT project_id, org_id FROM harness_sessions WHERE session_id=%s",
            (sid,),
        ).fetchone()
        assert row[0] is None and row[1] is not None


@pytest.fixture
def remote(monkeypatch, harness):
    state = SimpleNamespace(
        project=None,
        requests=[],
        audits=[],
        response={
            "stdout": "",
            "exit_code": 0,
            "outcome": "completed",
            "capabilities": list(HOOK_EVALUATOR_CAPABILITIES),
        },
        local=LocalSubsetEvaluation("", 0, False, {}),
    )
    monkeypatch.setattr(relay, "detect_executor", lambda: harness)
    monkeypatch.setattr(
        relay, "resolve_hook_project_scope", lambda p: HookProjectScope(state.project)
    )
    monkeypatch.setattr(relay, "lint_config_snapshot", lambda p: {})
    monkeypatch.setattr(relay, "evaluate_local_subset", lambda *a, **kw: state.local)
    monkeypatch.setattr(relay, "stamp_hook_input", lambda p, text, *a: (text, None))
    for name in [
        "_record_client_anchor",
        "_codex_capture",
        "settle_projection",
        "print_execution_provenance",
        "record_model_facts_shipped",
    ]:
        monkeypatch.setattr(relay, name, lambda *a, **kw: None)
    monkeypatch.setattr(
        "yoke_harness.hooks.cursor_lifecycle_hooks.ensure_user_lifecycle_hooks_for_executor",
        lambda executor: None,
    )
    for name in [
        "client_model_facts",
        "client_usage_facts",
        "observe_claude_presentation",
    ]:
        monkeypatch.setattr(identity_relay, name, lambda *a, **kw: {})
    for name in [
        "client_entrypoint",
        "client_executor_version",
        "client_native_thread_id",
    ]:
        monkeypatch.setattr(identity_relay, name, lambda *a: "test")
    monkeypatch.setattr(identity_relay, "client_machine_id", lambda: "machine")
    monkeypatch.setattr(
        relay, "relay_denial_audit", lambda c, a: state.audits.append(a)
    )

    def opener(request, **kwargs):
        state.requests.append(json.loads(request.data))
        return _FakeResponse(json.dumps(state.response).encode())

    state.run = lambda: relay.relay_hook_event(
        "UserPromptSubmit",
        HttpsConnection("https://env.example", "fixture-token"),
        stdin_data=json.dumps({"session_id": "test", "identity_stamped": True}),
        opener=opener,
    )
    return state


def test_outside_project_relays_hook_over_https(remote):
    assert remote.run() == 0
    assert remote.requests[0]["project_id"] is None
    assert remote.requests[0]["hook_schema"] == 1


@pytest.mark.parametrize("exit_code", [1, 2])
def test_relay_passes_standard_refusal_text_and_status_unchanged(
    remote, capsys, exit_code, harness
):
    refusal = (
        "function_argument_version_skew: sessions.begin machine_scope needs next-release. "
        "Recovery: start the agent inside a registered project folder."
    )
    remote.response.update(outcome="denied", stdout=refusal, exit_code=exit_code)
    assert remote.run() == exit_code
    out = capsys.readouterr()
    if harness == "claude-code" and exit_code == 2:
        assert not out.out
        assert out.err == format_hook_diagnostic("UserPromptSubmit", refusal) + "\n"
    else:
        assert out.out == refusal and not out.err


@pytest.mark.parametrize("metadata", [{}, {"capabilities": []}])
def test_relay_does_not_translate_refusal_when_capabilities_are_absent(
    remote, capsys, metadata
):
    remote.response.pop("capabilities")
    remote.response.update(
        outcome="denied", stdout="server refusal", exit_code=1, **metadata
    )
    assert remote.run() == 1
    out = capsys.readouterr()
    assert out.out == "server refusal" and not out.err


def test_relay_passes_guard_denial_on_projectless_request_unchanged(remote, capsys):
    remote.response.update(outcome="denied", stdout="guard denied", exit_code=1)
    assert remote.run() == 1
    assert capsys.readouterr().out == "guard denied"


def test_relay_passes_project_request_denial_unchanged(remote, capsys):
    remote.project = 1
    remote.response.update(
        outcome="denied", stdout="project guard", exit_code=1, capabilities=[]
    )
    assert remote.run() == 1
    assert capsys.readouterr().out == "project guard"


def test_machine_scope_local_denial_relays_audit(remote):
    remote.local = LocalSubsetEvaluation(
        "denied", 1, True, denial_audit={"session_id": "test"}
    )
    assert remote.run() == 1
    assert remote.audits == [{"session_id": "test"}]
    assert remote.requests == []


def test_evaluator_capabilities_include_machine_scope():
    from yoke_core.api.routes.hooks_wire_contract import HookEvaluateResponse

    assert HOOK_MACHINE_SCOPE_CAPABILITY in HOOK_EVALUATOR_CAPABILITIES
    for outcome in ["completed", "denied"]:
        response = HookEvaluateResponse(
            stdout="", exit_code=1, outcome=outcome, wait_ms=0, degraded=[]
        )
        assert HOOK_MACHINE_SCOPE_CAPABILITY in response.capabilities


def test_harness_sessions_begin_outside_project_registers_machine_scope(
    registration, harness, monkeypatch, capsys
):
    from yoke_core.hooks import sessions_cli

    sid = str(uuid4())
    monkeypatch.setattr(sessions_cli, "connect", db_helpers.connect)
    monkeypatch.setattr(
        "yoke_contracts.project_defaults.default_project_for_directory",
        lambda root: None,
    )
    sessions_cli.main(["begin", sid, harness, "test", "", "/tmp/unmapped"])
    assert "Began session" in capsys.readouterr().out
    row = registration.execute(
        "SELECT project_id, org_id, actor_id, reasoning_effort FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone()
    assert row[0] is None and row[1] is not None and row[2] is not None
    assert row[3] is None


def test_operator_begin_infers_machine_scope(registration, harness, monkeypatch):
    from yoke_core.api import service_client_sessions_lifecycle_begin as client

    sid = str(uuid4())
    monkeypatch.setattr(client, "_project_id_from_args", lambda *a: None)
    monkeypatch.setattr(client, "_get_db_readwrite", db_helpers.connect)
    args = ["--session-id", sid, "--executor", harness]
    args += ["--provider", "test", "--workspace", "/tmp/unmapped"]
    args += ["--machine-id", str(uuid4())]
    assert client.cmd_session_begin(args) == 0
    row = registration.execute(
        "SELECT project_id, org_id, actor_id FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone()
    assert row[0] is None and row[1] is not None and row[2] is not None
