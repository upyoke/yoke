"""The deployed probe must prove the runner's endpoint through public CLI calls."""

import pytest
from types import SimpleNamespace

from runtime.api.tools import agent_control_plane_probe as probe


@pytest.mark.parametrize(
    "base_url,connection",
    [
        ("", {"transport": "https", "api_url": "https://candidate.test"}),
        ("https://candidate.test", {"transport": "local"}),
        (
            "https://candidate.test",
            {"transport": "https", "api_url": "https://other.test"},
        ),
        (
            "https://candidate.test",
            {"transport": "https", "api_url": "http://candidate.test"},
        ),
        (
            "https://candidate.test",
            {
                "transport": "https",
                "api_url": "https://candidate.test:8443/api/orgs/team",
            },
        ),
        (
            "https://candidate.test",
            {"transport": "https", "api_url": "https://candidate.test:0/api/orgs/team"},
        ),
        (
            "https://candidate.test",
            {"transport": "https", "api_url": "https://candidate.test:invalid"},
        ),
        (
            "https://candidate.test",
            {"transport": "https", "api_url": "https://user@candidate.test"},
        ),
    ],
)
def test_wrong_target_refuses_before_public_calls(
    monkeypatch, capsys, base_url, connection
):
    monkeypatch.setenv("BASE_URL", base_url)
    monkeypatch.setenv("DEPLOYMENT_MEMBER_REF", "YOK-42")
    monkeypatch.setenv("YOKE_PROJECT", "fixture-project")
    monkeypatch.setattr(probe, "active_connection", lambda: connection)
    monkeypatch.setattr(
        probe, "call", lambda *a, **k: pytest.fail("wrong endpoint called")
    )
    assert probe.main() == 1
    assert "agent_route_target_mismatch" in capsys.readouterr().err


@pytest.mark.parametrize(
    "api_url",
    [
        "https://candidate.test",
        "https://candidate.test/api/orgs/team",
        "https://CANDIDATE.test:443/api/orgs/team/",
    ],
)
def test_same_origin_accepts_organization_api_path_without_rewriting(
    monkeypatch, api_url
):
    monkeypatch.setenv("BASE_URL", "https://candidate.test/")
    connection = {"transport": "https", "api_url": api_url}
    monkeypatch.setattr(
        probe,
        "active_connection",
        lambda: connection,
    )
    probe.require_target()
    assert connection["api_url"] == api_url


def test_probe_uses_runner_project_without_reading_full_item(monkeypatch):
    member = f"YOK-{42}"
    project = "fixture-project"
    monkeypatch.setenv("DEPLOYMENT_MEMBER_REF", member)
    monkeypatch.setenv("YOKE_PROJECT", project)
    monkeypatch.setattr(probe, "require_target", lambda: None)
    calls = []

    def call(*args, **kwargs):
        calls.append(args)
        if args[0] == "advance":
            return {"blockers": []}
        assert args[:3] == ("ouroboros", "reflection", "capture")
        return dict.fromkeys(
            [
                "entries_parsed",
                "entries_persisted",
                "entries_persist_failed",
                "entries_duplicate_skipped",
            ],
            0,
        ) | {"errors": [], "blocks_seen": 1}

    monkeypatch.setattr(probe, "call", call)
    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="# Merge Readiness Audit", stderr=""
        ),
    )
    assert probe.main() == 0
    assert calls[1][calls[1].index("--project") + 1] == project
