"""Physical acceptance checks both stores and always tears down its server."""

from pathlib import Path

import pytest

from runtime.api.tools import feedback_terminal_acceptance as probe


@pytest.mark.parametrize("wrong_agent", [False, True])
def test_physical_probe_checks_rows_and_cleans_up(monkeypatch, wrong_agent):
    calls = []
    rows = {}
    next_id = 1
    version = "0.2.0.202610290013"
    fingerprint = "fixture@2026-01-01T00:00:00Z"

    def command(*args, env=None, parse=True):
        nonlocal next_id
        calls.append(args)
        if args[:2] == ("self-host", "init"):
            bundle = Path(args[args.index("--dir") + 1])
            bundle.mkdir()
            (bundle / "docker-compose.yml").write_text("services: {}")
        if args[0] == "status":
            return {"runtime_identity": {"version": version}}
        if args[:2] == ("organizations", "get"):
            slug, timestamp = fingerprint.split("@")
            return {"result": {"slug": slug, "created_at": timestamp}}
        if args[0] == "feedback" and "--to" in args:
            note_id = str(next_id)
            next_id += 1
            rows[note_id] = {"yoke_version": version, "universe_fingerprint": fingerprint,
                             "agent": "unknown" if wrong_agent else "terminal",
                             "body": args[args.index("--evidence") + 1]}
            return {"entry_id": note_id}
        if args[:2] == ("feedback", "get"):
            return {"result": {"entry": rows[args[2]]}}
        return {}

    monkeypatch.setattr(probe, "command", command)
    if wrong_agent:
        with pytest.raises(AssertionError):
            probe.main()
    else:
        assert probe.main() == 0
        assert len(rows) == 4
    assert any(args[:2] == ("feedback", "archive") for args in calls)
    assert calls[-1][:2] == ("self-host", "teardown")
