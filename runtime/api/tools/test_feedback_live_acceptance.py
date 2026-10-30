"""Live feedback acceptance never leaves a successful cleanup failure."""

from runtime.api.tools import feedback_live_acceptance as probe
import subprocess
import pytest


def test_failed_inner_command_keeps_its_stderr(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda *_a, **_k: "/fixture/yoke")
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
    monkeypatch.setattr(probe, "negative_probes", lambda *_: None)
