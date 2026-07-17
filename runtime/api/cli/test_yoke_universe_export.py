"""Tests for the ``yoke universe export`` tool-shaped adapter.

The engine half is stubbed at the dynamic-import seam
(``local_universe_setup._export_engine``); the real dump/authority
behavior is covered by ``runtime/api/domain/test_universe_export.py``.
These tests pin the client half: argument plumbing, JSON/human output,
error surfacing, and tool-shaped command resolution.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands import local_universe as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import local_universe_setup as setup
from yoke_cli.transport.https import HttpsConnection


def _stub_export_engine(report=None, error: str | None = None):
    def export_universe(*, out, emit):
        if error is not None:
            raise RuntimeError(error)
        emit("  [universe-export] dumping org 'default' universe")
        payload = dict(report or {})
        # The engine contract takes the raw --out text (str | Path | None)
        # and owns expansion/routing; mirror the str-accepting shape here.
        out_dir = Path(out).expanduser() if out else Path("/cwd")
        payload.setdefault(
            "artifact",
            str(out_dir / "default-universe-20260706T000000Z.tar"),
        )
        payload.setdefault("bytes", 4096)
        payload.setdefault("format", "universe-tar")
        payload.setdefault("org", "default")
        return payload

    return SimpleNamespace(export_universe=export_universe)


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_export_json_reports_artifact(monkeypatch, machine_home, tmp_path, capsys):
    monkeypatch.setattr(setup, "_export_engine", _stub_export_engine)

    assert commands.universe_export(["--out", str(tmp_path), "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["artifact"].startswith(str(tmp_path))
    assert report["artifact"].endswith(".tar")
    assert report["org"] == "default"
    assert report["format"] == "universe-tar"


def test_export_human_summary_names_artifact_org_and_format(
    monkeypatch, machine_home, capsys,
):
    monkeypatch.setattr(setup, "_export_engine", _stub_export_engine)

    assert commands.universe_export([]) == 0

    out = capsys.readouterr().out
    assert "universe export: " in out
    assert "org: default" in out
    assert "format: universe-tar" in out


def test_export_engine_refusal_is_reported_cleanly(
    monkeypatch, machine_home, capsys,
):
    monkeypatch.setattr(
        setup, "_export_engine",
        lambda: _stub_export_engine(
            error="the active connection 'prod' is prod-flagged",
        ),
    )

    assert commands.universe_export([]) == 1
    err = capsys.readouterr().err
    assert "error: " in err
    assert "prod-flagged" in err


def test_tool_shaped_resolution_covers_universe_export():
    resolved = resolve_tool_shaped(["universe", "export", "--json"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.universe_export
    assert remaining == ["--json"]


def test_export_uses_self_host_https_download(monkeypatch, capsys, tmp_path):
    connection = HttpsConnection(
        api_url="https://yoke.example.test",
        token="token",
        env="self-host",
    )
    calls = []
    monkeypatch.setattr(commands, "resolve_https_connection", lambda: connection)
    monkeypatch.setattr(
        commands,
        "download_universe",
        lambda selected, *, out: calls.append((selected, out)) or {
            "artifact": str(tmp_path / "acme.tar"),
            "bytes": 12,
            "format": "universe-tar",
            "org": "acme",
        },
    )

    assert commands.universe_export(["--out", str(tmp_path), "--json"]) == 0
    assert calls == [(connection, str(tmp_path))]
    assert json.loads(capsys.readouterr().out)["org"] == "acme"


def test_hosted_export_stays_on_platform_guidance(monkeypatch, capsys):
    connection = HttpsConnection(
        api_url="https://app.stage.upyoke.com/api/orgs/acme",
        token="token",
        env="stage",
    )
    monkeypatch.setattr(commands, "resolve_https_connection", lambda: connection)
    monkeypatch.setattr(
        setup,
        "_export_engine",
        lambda: _stub_export_engine(error="hosted org admins use the dashboard"),
    )
    monkeypatch.setattr(
        commands,
        "download_universe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hosted export must not use self-host endpoint")
        ),
    )

    assert commands.universe_export([]) == 1
    assert "dashboard" in capsys.readouterr().err
