"""Closing a private check cannot stop the authoritative identity browser."""

from contextlib import contextmanager
import json

from yoke_cli.commands.qa_browser_stop import qa_browser_stop


def test_stop_requires_the_check_id(capsys):
    assert qa_browser_stop(["--project", "fixture", "--json"]) == 2
    assert "--check-id" in capsys.readouterr().err


def test_stop_closes_only_the_named_check(monkeypatch, capsys):
    closed = []

    @contextmanager
    def scope(project, identity, **kwargs):
        assert (project, identity, kwargs) == (
            "fixture",
            "admin",
            {"check_id": "opaque"},
        )
        yield
        closed.append("opaque")

    monkeypatch.setattr("yoke_harness.browser_check_profile.check_scope", scope)
    assert (
        qa_browser_stop(
            [
                "--project",
                "fixture",
                "--identity",
                "admin",
                "--check-id",
                "opaque",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"status": "stopped"}
    assert closed == ["opaque"]


def test_unknown_check_names_recovery(capsys):
    assert qa_browser_stop(["--project", "fixture", "--check-id", "invalid"]) == 1
    assert "browser_check_unavailable" in capsys.readouterr().err
