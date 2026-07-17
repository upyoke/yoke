"""Tests for the ticketless local-universe import product command."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_cli.commands import local_universe as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import local_universe_setup as setup


def _engine(report=None, error: str | None = None):
    def import_universe(archive):
        if error is not None:
            raise RuntimeError(error)
        return dict(report or {
            "ok": True,
            "org": "acme",
            "actor_label": "operator",
            "archive": {"path": str(archive)},
        })

    return SimpleNamespace(import_universe=import_universe)


def test_import_json_reports_local_owner(monkeypatch, capsys):
    monkeypatch.setattr(setup, "_import_engine", _engine)
    assert commands.universe_import(["archive.tar", "--yes", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["org"] == "acme"
    assert report["actor_label"] == "operator"
    assert report["archive"]["path"] == "archive.tar"


def test_import_human_summary(monkeypatch, capsys):
    monkeypatch.setattr(setup, "_import_engine", _engine)
    assert commands.universe_import(["archive.tar", "--yes"]) == 0
    output = capsys.readouterr().out
    assert "universe imported: acme" in output
    assert "local owner: operator" in output
    assert "archive: archive.tar" in output


def test_import_requires_noninteractive_consent(monkeypatch, capsys):
    monkeypatch.setattr(commands.sys.stdin, "isatty", lambda: False)
    assert commands.universe_import(["archive.tar"]) == 1
    assert "pass --yes" in capsys.readouterr().err


def test_import_refusal_is_reported(monkeypatch, capsys):
    monkeypatch.setattr(
        setup,
        "_import_engine",
        lambda: _engine(error="active connection is not the machine-local universe"),
    )
    assert commands.universe_import(["archive.tar", "--yes"]) == 1
    assert "machine-local universe" in capsys.readouterr().err


def test_tool_shaped_resolution_covers_universe_import():
    resolved = resolve_tool_shaped(["universe", "import", "archive.tar", "--yes"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.universe_import
    assert remaining == ["archive.tar", "--yes"]
