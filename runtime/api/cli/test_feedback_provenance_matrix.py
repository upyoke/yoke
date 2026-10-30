"""CLI provenance survives install, session, surface and storage boundaries."""

import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from yoke_cli import feedback_reporter as reporter
from yoke_cli.commands.adapters.feedback import feedback_append
from yoke_contracts import runtime_identity
from yoke_contracts.feedback_provenance import FeedbackIdentityError
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionCallResponse, FunctionError, TargetRef
from yoke_core.domain.ouroboros_entry_insert import cmd_insert_entry

VERSION = "0.2.0.202610290013"
FINGERPRINT = "fixture@2026-01-01T00:00:00Z"
COMMIT = "abcdef0123456789abcdef0123456789abcdef01"
CLOCK = "2026-10-29T00:13:00+00:00"


@pytest.fixture(params=["sqlite-local", "postgres-tenant"])
def storage(request, tmp_path):
    if request.param == "postgres-tenant":
        from runtime.api.fixtures.file_test_db import init_test_db, connect_test_db
        with init_test_db(tmp_path) as token:
            with connect_test_db(token) as conn:
                yield conn
        return
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ouroboros_entries (id INTEGER PRIMARY KEY, timestamp TEXT, "
                 "agent TEXT, category TEXT, body TEXT, project_id INTEGER, target_project_id INTEGER, "
                 "created_at TEXT, correlation_id INTEGER, session_id TEXT, actor_id INTEGER, "
                 "reporter_email TEXT, yoke_version TEXT, universe_fingerprint TEXT)")
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.parametrize("install", ["wheel", "source", "editable", "worktree", "dirty"])
@pytest.mark.parametrize("destination", ["yoke", "universe"])
@pytest.mark.parametrize("session", ["harness-session", None])
@pytest.mark.parametrize("surface", ["claude-code", "codex", "cursor", None])
def test_stored_identity_matrix(monkeypatch, tmp_path, storage, install, destination, session, surface):
    root = tmp_path / install
    monkeypatch.setattr(runtime_identity, "source_checkout_root", lambda module: None if install == "wheel" else root)
    monkeypatch.setattr(runtime_identity, "local_handshake_version", lambda: VERSION)

    def git(args, **kwargs):
        assert args[:3] == ["git", "-C", str(root)]
        output = COMMIT + "\n" + CLOCK if args[3] == "show" else (" M source.py" if install == "dirty" else "")
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr("subprocess.run", git)
    monkeypatch.setattr(reporter, "running_harness_family", lambda: surface)
    monkeypatch.setattr("yoke_contracts.session_identity.resolve_actor_role", lambda: None)
    monkeypatch.setattr(reporter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(reporter, "harness_email", lambda *_: None)
    monkeypatch.setattr(reporter, "git_email", lambda *_: None)

    def provenance(**kwargs):
        assert kwargs["function_id"] == "feedback.provenance.get"
        return SimpleNamespace(success=True, result={"universe_fingerprint": FINGERPRINT, "actor_email": "actor@example.test"})

    monkeypatch.setattr(reporter, "call_dispatcher", provenance)
    monkeypatch.setattr("yoke_cli.commands.adapters.feedback.client_project_context", lambda: None)
    recorded = []

    def store(payload):
        recorded.append(payload)
        return cmd_insert_entry(storage, CLOCK, payload["agent"], payload["category"], payload["evidence"],
                                yoke_version=payload["yoke_version"], universe_fingerprint=FINGERPRINT,
                                reporter_email=payload.get("reporter_email"))

    def public(request, timeout):
        payload = json.loads(request.data)
        assert request.get_header("User-agent") == "yoke-cli/" + payload["yoke_version"]
        assert payload["universe_fingerprint"] == FINGERPRINT
        result = io.BytesIO(json.dumps({"entry_id": store(payload)}).encode())
        result.status = 201
        return result

    def universe(**kwargs):
        assert kwargs["function_id"] == "ouroboros.field_note.append"
        assert "universe_fingerprint" not in kwargs["payload"]
        store(kwargs["payload"])
        return 0

    monkeypatch.setattr("yoke_cli.feedback_delivery.open_no_redirect", public)
    monkeypatch.setattr("yoke_cli.commands.adapters.feedback.dispatch_and_emit", universe)
    args = ["--to", destination, "--category", "observation", "--evidence", "matrix evidence"]
    if session:
        args += ["--session-id", session]
    assert feedback_append(args) == 0
    row = storage.execute("SELECT yoke_version, universe_fingerprint, agent FROM ouroboros_entries").fetchone()
    expected = VERSION if install == "wheel" else VERSION + "+" + COMMIT[:12] + (".dirty" if install == "dirty" else "")
    assert tuple(row) == (expected, FINGERPRINT, surface or "terminal")
    assert recorded[0]["reporter_email"] == "actor@example.test"


@pytest.mark.parametrize("destination", ["yoke", "universe"])
@pytest.mark.parametrize("field", ["yoke_version", "universe_fingerprint"])
def test_unreadable_identity_refuses_before_delivery(monkeypatch, capsys, destination, field):
    monkeypatch.setattr(reporter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(reporter, "call_dispatcher", lambda **_: SimpleNamespace(success=False, error=None))
    monkeypatch.setattr(reporter, "_bound_fingerprint", lambda: "")
    if field == "yoke_version":
        def broken():
            raise ValueError("missing metadata")
        monkeypatch.setattr(runtime_identity, "reporting_version", broken)
    else:
        monkeypatch.setattr(runtime_identity, "reporting_version", lambda: VERSION)
    monkeypatch.setattr("yoke_cli.feedback_delivery.open_no_redirect", lambda *_a, **_k: pytest.fail("HTTP delivery"))
    monkeypatch.setattr("yoke_cli.commands.adapters.feedback.dispatch_and_emit", lambda **_: pytest.fail("universe delivery"))
    evidence = "Keep all evidence for retry"
    assert feedback_append(["--to", destination, "--category", "failed", "--evidence", evidence]) == 1
    diagnostic = capsys.readouterr().err
    assert f"feedback_provenance_unavailable: {field}" in diagnostic
    assert evidence in diagnostic


def test_saved_identity_and_role_survive_an_unreachable_server(monkeypatch):
    monkeypatch.setattr(runtime_identity, "reporting_version", lambda: VERSION)
    monkeypatch.setattr(reporter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(reporter, "call_dispatcher", lambda **_: SimpleNamespace(success=False, error=None))
    monkeypatch.setattr(reporter, "_bound_fingerprint", lambda: FINGERPRINT)
    monkeypatch.setattr("yoke_contracts.session_identity.resolve_actor_role", lambda: "engineer")
    assert reporter.feedback_provenance()["agent"] == "engineer"
    assert reporter.feedback_provenance()["universe_fingerprint"] == FINGERPRINT


@pytest.mark.parametrize("field", ["yoke_version", "universe_fingerprint", "agent"])
def test_writer_rejects_incomplete_identity(storage, field):
    payload = {"yoke_version": VERSION, "universe_fingerprint": FINGERPRINT, "agent": "terminal"}
    payload[field] = None
    with pytest.raises(FeedbackIdentityError):
        cmd_insert_entry(storage, CLOCK, payload.pop("agent"), "failed", "writer guard", **payload)
    assert storage.execute("SELECT count(*) FROM ouroboros_entries").fetchone()[0] == 0


def test_pre_floor_server_refuses_new_provenance_function():
    from yoke_cli.transport.function_version_skew import retype_skew
    request = FunctionCallRequest(function="feedback.provenance.get", target=TargetRef(kind="global"))
    response = FunctionCallResponse(success=False, function=request.function, version=request.version,
                                    request_id=request.request_id,
                                    error=FunctionError(code="function_not_registered", message="old registry"))
    answer = retype_skew(response, request, server_version=VERSION, env_name="tenant")
    assert answer.error.code == "function_version_skew"
    assert "minimum serving version next-release" in answer.error.message


def test_universe_skew_refuses_before_the_old_writer(monkeypatch, capsys):
    error = FunctionError(code="function_version_skew", message="minimum serving version next-release",
                          recovery_hint="Escalate to the control-plane operator.")
    monkeypatch.setattr(runtime_identity, "reporting_version", lambda: VERSION)
    monkeypatch.setattr(reporter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(reporter, "call_dispatcher", lambda **_: SimpleNamespace(success=False, error=error))
    monkeypatch.setattr(reporter, "_bound_fingerprint", lambda: FINGERPRINT)
    monkeypatch.setattr("yoke_cli.commands.adapters.feedback.dispatch_and_emit", lambda **_: pytest.fail("old writer"))
    assert feedback_append(["--to", "universe", "--category", "failed", "--evidence", "skew probe"]) != 0
    assert "function_version_skew" in capsys.readouterr().err


def test_reporting_version_uses_loaded_module_not_cwd(monkeypatch, tmp_path):
    import yoke_cli
    root = tmp_path / "loaded"
    (root / "runtime/harness").mkdir(parents=True)
    (root / "pyproject.toml").write_text('name = "yoke"')
    module = root / "packages/yoke-cli/src/yoke_cli/__init__.py"
    monkeypatch.setattr(yoke_cli, "__file__", str(module))
    monkeypatch.chdir(tmp_path)
    def git(args, **_):
        assert args[:3] == ["git", "-C", str(root)]
        return SimpleNamespace(stdout=COMMIT + "\n" + CLOCK if args[3] == "show" else "")
    monkeypatch.setattr("subprocess.run", git)
    assert runtime_identity.reporting_version() == VERSION + "+" + COMMIT[:12]
