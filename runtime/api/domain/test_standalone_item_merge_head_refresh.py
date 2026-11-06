"""Candidate refresh precedes commit-bound merge readiness."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_cli as cli


@pytest.mark.parametrize("check", [False, True])
def test_readiness_uses_refreshed_item_only_for_actual_merge(monkeypatch, check):
    stale = {"id": 7, "public_ref": "ITEM-7", "workflow": {"id": "dash"}}
    fresh = {**stale, "worktrees": [{"commit_sha": "a" * 40}]}
    events = []
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (stale, ""))
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    def refresh(item, resolve):
        assert item is stale
        assert resolve() == (stale, "")
        events.append("refresh")
        return fresh, ""
    def assess(item, *_a, **_k):
        assert item is (stale if check else fresh)
        events.append("readiness")
        return SimpleNamespace(ready=False, refusal=lambda: "stop at readiness")
    monkeypatch.setattr(cli, "refresh_recorded_head", refresh)
    monkeypatch.setattr(cli.readiness_gate, "assess", assess)
    monkeypatch.setattr(cli.readiness_gate, "print_check", lambda *_a, **_k: 1)
    monkeypatch.setattr(cli.report, "fail_json", lambda *_a, **_k: 1)
    assert cli.run(["ITEM-7"] + (["--check"] if check else [])) == 1
    assert events == (["readiness"] if check else ["refresh", "readiness"])


def test_recording_refusal_never_reaches_readiness(monkeypatch):
    item = {"id": 7, "public_ref": "ITEM-7", "workflow": {"id": "dash"}}
    monkeypatch.setattr(cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(cli.report, "bind", lambda **_k: lambda *_a, **_kw: None)
    monkeypatch.setattr(cli, "refresh_recorded_head", lambda *_a: (item, "record failed"))
    monkeypatch.setattr(cli.readiness_gate, "assess", lambda *_a, **_k: pytest.fail("readiness ran"))
    errors = []
    monkeypatch.setattr(cli.report, "fail_json", lambda message, **_k: errors.append(message) or 1)
    assert cli.run(["ITEM-7"]) == 1
    assert errors == ["record failed"]
