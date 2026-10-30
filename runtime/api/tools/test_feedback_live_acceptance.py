"""Live feedback acceptance never leaves a successful cleanup failure."""

from runtime.api.tools import feedback_live_acceptance as probe
import subprocess
import pytest


def test_failed_inner_command_keeps_its_stderr(monkeypatch):
    diagnostic = "feedback_delivery_failed: HTTP 400: feedback_user_agent_invalid"
    monkeypatch.setattr(probe.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, "", diagnostic))
    with pytest.raises(RuntimeError, match=diagnostic):
        probe.call("feedback", "--to", "yoke")


def test_success_reads_then_archives_only_the_received_note(monkeypatch):
    monkeypatch.delenv("YOKE_FEEDBACK_URL", raising=False)
    calls = []
    evidence = None
    def call(*args):
        nonlocal evidence
        calls.append(args)
        if "--to" in args:
            evidence = args[args.index("--evidence") + 1]
            return {"entry_id": "14"}
        if args[1] == "get":
            return {"result": {"entry": {"body": evidence, "category": "observation", "project": "yoke", "actor_id": 5, "universe_fingerprint": probe.PRODUCTION_FINGERPRINT, "yoke_version": "0.2.0.202610290013", "agent": "terminal"}}}
        return {"success": True}
    monkeypatch.setattr(probe, "call", call)
    assert probe.main() == 0
    assert calls[-1] == ("feedback", "archive", "14", "--project", "yoke")


def test_cleanup_failure_fails_the_case(monkeypatch):
    monkeypatch.delenv("YOKE_FEEDBACK_URL", raising=False)
    def call(*args):
        if "--to" in args:
            return {"entry_id": "15"}
        raise RuntimeError("fixture refusal")
    monkeypatch.setattr(probe, "call", call)
    assert probe.main() == 1


@pytest.fixture(autouse=True)
def _expected_identity(monkeypatch):
    monkeypatch.setattr(probe, "expected_version", lambda: "0.2.0.202610290013")
    monkeypatch.setattr(probe, "running_harness_family", lambda: None)
    monkeypatch.setattr(probe, "resolve_actor_role", lambda: None)
    monkeypatch.setattr(probe, "negative_probes", lambda *_: None)


@pytest.mark.parametrize("value", ["0.2.0.202610300001", "0.2.0.202610300001+abcdef012345", "0.2.0.202610300001+abcdef012345.dirty"])
def test_expected_version_accepts_the_bound_cli_identity(monkeypatch, value):
    from yoke_contracts import runtime_identity
    monkeypatch.setattr(runtime_identity, "reporting_version", lambda: value)
    monkeypatch.setattr(probe, "run", lambda *_: pytest.fail("status display is not reporting identity"))
    assert _real_expected_version() == value


@pytest.mark.parametrize("value", ["source", "unknown", "0.2.0.dev1+abcdef012345", None])
def test_invalid_reporting_identity_names_the_actual_value(monkeypatch, value):
    from yoke_contracts import runtime_identity
    monkeypatch.setattr(runtime_identity, "reporting_version", lambda: value)
    with pytest.raises(RuntimeError) as error:
        _real_expected_version()
    assert repr(value) in str(error.value)
    assert "yoke dev run" in str(error.value)


def test_child_keeps_candidate_source_environment(monkeypatch):
    monkeypatch.setenv("YOKE_ENV", "stage")
    monkeypatch.setenv("YOKE_SOURCE_DEV_RUN_ROOT", "/var/folders/candidate")
    monkeypatch.setenv("PYTHONPATH", "/var/folders/candidate/packages/yoke-cli/src")
    def child(argv, **kwargs):
        import os
        assert argv == ["yoke", "status", "--json"]
        assert "env" not in kwargs
        assert os.environ["YOKE_SOURCE_DEV_RUN_ROOT"] == "/var/folders/candidate"
        assert os.environ["PYTHONPATH"].endswith("/packages/yoke-cli/src")
        assert os.environ["YOKE_ENV"] == "stage"
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")
    monkeypatch.setattr(probe.subprocess, "run", child)
    assert probe.run("status") == {"ok": True}


_real_expected_version = probe.expected_version
