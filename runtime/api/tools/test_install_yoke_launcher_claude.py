"""Claude.app preference tests for ``install_yoke_launcher``."""

from __future__ import annotations

import io
import json
from pathlib import Path

from yoke_core.tools import install_yoke_launcher as isl


def _claude_config_at(tmp_path: Path, payload: dict | None) -> Path:
    p = tmp_path / "claude_desktop_config.json"
    if payload is not None:
        p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return p


def test_claude_bypass_noop_on_non_darwin(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "linux")
    cfg = _claude_config_at(tmp_path, {"preferences": {}})
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is False
    assert stream.getvalue() == ""
    assert json.loads(cfg.read_text()) == {"preferences": {}}


def test_claude_bypass_noop_when_config_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = tmp_path / "absent.json"
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is False
    assert stream.getvalue() == ""


def test_claude_bypass_noop_when_already_true(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = _claude_config_at(
        tmp_path,
        {"preferences": {"bypassPermissionsModeEnabled": True, "other": "kept"}},
    )
    before = cfg.read_text()
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is False
    assert stream.getvalue() == ""
    assert cfg.read_text() == before


def test_claude_bypass_respects_explicit_false(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = _claude_config_at(
        tmp_path,
        {"preferences": {"bypassPermissionsModeEnabled": False, "other": "kept"}},
    )
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is False
    assert stream.getvalue() == ""
    data = json.loads(cfg.read_text())
    assert data["preferences"]["bypassPermissionsModeEnabled"] is False


def test_claude_bypass_sets_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = _claude_config_at(
        tmp_path,
        {
            "preferences": {
                "remoteToolsDeviceName": "current-mac",
                "sidebarMode": "epitaxy",
            },
        },
    )
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is True
    data = json.loads(cfg.read_text())
    assert data["preferences"]["bypassPermissionsModeEnabled"] is True
    assert data["preferences"]["remoteToolsDeviceName"] == "current-mac"
    assert data["preferences"]["sidebarMode"] == "epitaxy"
    out = stream.getvalue().lower()
    assert "bypasspermissionsmodeenabled" in out
    assert "claude.app" in out


def test_claude_bypass_atomic_write_no_tmp_left_behind(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = _claude_config_at(tmp_path, {"preferences": {}})
    isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=io.StringIO()
    )
    tmp_leftover = cfg.with_suffix(cfg.suffix + ".yoke-tmp")
    assert not tmp_leftover.exists()


def test_claude_bypass_handles_malformed_json(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl.sys, "platform", "darwin")
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("not valid json{", encoding="utf-8")
    stream = io.StringIO()
    assert isl.configure_claude_app_bypass_permissions(
        config_path=cfg, stream=stream
    ) is False
    assert "could not parse" in stream.getvalue().lower()
    assert cfg.read_text() == "not valid json{"
