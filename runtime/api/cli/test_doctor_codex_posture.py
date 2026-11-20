"""Doctor and sandbox refusals use the actual Codex turn before touching Postgres."""

import json

import pytest

from yoke_cli import sandbox_denial
from yoke_cli.commands.adapters import doctor
from yoke_cli.commands import local_dispatch_preload
from yoke_cli.engine_upgrade_convergence import LocalUniverseConvergenceError
from yoke_cli.main import main
from yoke_contracts import harness_family_identity
from yoke_harness.hooks import identity_codex_runtime

SESSION = "67cb0424-7066-4b1d-9101-9b838ba638bd"
UNATTENDED_CONFIG = 'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
RESTRICTED_CONFIG = 'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n'


@pytest.fixture
def codex_turn(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    transcript = sessions / f"rollout-{SESSION}.jsonl"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("CODEX_SESSION_ID", SESSION)
    monkeypatch.setattr(harness_family_identity, "nearest_harness_family", lambda: "codex")
    monkeypatch.setattr(identity_codex_runtime, "_codex_resolve_entrypoint", lambda _sid: "codex-desktop")

    def write(*, saved=UNATTENDED_CONFIG, restricted=True):
        (tmp_path / "config.toml").write_text(saved, encoding="utf-8")
        rows = [
            {"type": "session_meta", "payload": {"id": SESSION}},
            {
                "type": "turn_context",
                "payload": {
                    "approval_policy": "on-request" if restricted else "never",
                    "sandbox_policy": {
                        "type": "workspace-write" if restricted else "danger-full-access",
                    },
                },
            },
        ]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    return write


@pytest.mark.parametrize("args", [[], ["run", "--quick"], ["run", "--session"]])
def test_restricted_doctor_refuses_before_connection_checks(args, codex_turn, monkeypatch, capsys):
    codex_turn()
    monkeypatch.setattr(doctor, "connection_failure", lambda: pytest.fail("Doctor touched the connection"))
    assert main(["doctor", *args]) == 1
    result = capsys.readouterr()
    (message,) = result.err.strip().splitlines()
    assert message.count("HARNESS_POSTURE_RESTRICTED") == 1
    assert "Full Access" in message and "new turn" in message
    assert "harness-setup --fix" not in message
    assert result.out == ""


def test_doctor_runs_quick_checks_once_the_turn_has_full_access(codex_turn, monkeypatch):
    # The live turn can have Full Access even when the saved settings ask.
    codex_turn(saved=RESTRICTED_CONFIG, restricted=False)
    monkeypatch.setattr(doctor, "connection_failure", lambda: None)
    monkeypatch.setattr(doctor, "required_project_context", lambda _project: "example")
    monkeypatch.setattr(doctor, "_active_transport_is_https", lambda: False)

    def dispatch(**kwargs):
        assert kwargs["payload"]["quick"] is True
        return 0

    monkeypatch.setattr(doctor, "_dispatch_in_process", dispatch)
    assert main(["doctor"]) == 0


@pytest.mark.parametrize("denial", [
    'pg_ctl: could not open log file "server.log": Operation not permitted',
    'pg_ctl: could not open log file "server.log": Permission denied',
    'pg_ctl: could not open log file "server.log": Access is denied.',
    "An attempt was made to access a socket in a way forbidden by its access permissions.",
])
@pytest.mark.parametrize("saved", [UNATTENDED_CONFIG, RESTRICTED_CONFIG])
def test_sandbox_recovery_names_the_reachable_fix(codex_turn, denial, saved):
    codex_turn(saved=saved)
    message = sandbox_denial.diagnose(RuntimeError(denial), ["sessions", "identity"])
    assert message
    assert denial in message
    assert "Full Access" in message and "new turn" in message
    assert ("harness-setup --fix" in message) == (saved == RESTRICTED_CONFIG)


def test_full_access_does_not_attribute_a_permission_error_to_codex(codex_turn):
    codex_turn(restricted=False)
    assert sandbox_denial.diagnose(PermissionError(1, "Operation not permitted"), []) is None


def test_local_start_failure_reaches_the_sandbox_diagnosis(codex_turn, monkeypatch, capsys):
    from yoke_cli import engine_upgrade_convergence

    codex_turn()
    monkeypatch.setattr(local_dispatch_preload, "_convergence_attempted", False)
    denial = "pg_ctl: could not open log file: Access is denied"

    def refuse(**_kwargs):
        raise LocalUniverseConvergenceError(denial)

    monkeypatch.setattr(engine_upgrade_convergence, "converge_for_serving", refuse)
    with pytest.raises(SystemExit) as stopped:
        local_dispatch_preload._converge_local_universe()
    assert stopped.value.code == 1
    message = capsys.readouterr().err
    assert message.count(denial) == 1
    assert "Full Access" in message
