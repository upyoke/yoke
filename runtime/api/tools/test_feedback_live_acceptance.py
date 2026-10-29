"""Live feedback acceptance never leaves a successful cleanup failure."""

from runtime.api.tools import feedback_live_acceptance as probe


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
            return {"result": {"entry": {"body": evidence, "category": "observation", "project": "yoke", "actor_id": 5, "universe_fingerprint": "org@time", "yoke_version": "version"}}}
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
