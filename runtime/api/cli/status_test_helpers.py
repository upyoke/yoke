"""Shared fixtures for machine-status CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.config import server_connect, status_server


def stub_server(monkeypatch, health):
    """Pin both status probes so tests never touch the network."""
    monkeypatch.setattr(
        status_server,
        "fetch_server_health",
        lambda api_url, timeout_s=None: health,
    )
    monkeypatch.setattr(
        server_connect,
        "verify_server_identity",
        lambda api_url, token, timeout_s=None: {
            "actor": {"id": 7, "label": "status-actor"},
            "token": {"name": "status-token"},
        },
    )


def status_config(tmp_path: Path, repo: Path) -> Path:
    temp_root = tmp_path / "tmp"
    cache_dir = tmp_path / "cache"
    temp_root.mkdir()
    cache_dir.mkdir()
    (repo / ".yoke").mkdir(parents=True)
    (repo / ".yoke" / "board.json").write_text(
        json.dumps({"timeline_widget": "always", "dashboard_weather": False}),
        encoding="utf-8",
    )
    token_file = tmp_path / "actor-token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "prod": True,
                    "api_url": "https://app.upyoke.com/api/orgs/acme",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(token_file),
                    },
                },
            },
            "temp_root": str(temp_root),
            "cache_dir": str(cache_dir),
            "projects": {
                str(repo.resolve()): {
                    "project_id": 1,
                    "board": {
                        "scope": "all",
                        "render_path": ".yoke/BOARD-ALL.md",
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


__all__ = ["status_config", "stub_server"]
