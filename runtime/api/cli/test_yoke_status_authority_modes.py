"""Authority proof coverage across hosted, self-hosted, and local modes."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import server_connect, status_render, status_server
from yoke_cli.transport import https as https_transport

from runtime.api.cli.status_test_helpers import status_config, stub_server


def test_status_https_reports_server_identity(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = status_config(tmp_path, repo)
    stub_server(
        monkeypatch, {"engine_version": "2.0.0", "build": "abc123def456"},
    )

    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["server"] == {
        "relevant": True,
        "reachable": True,
        "engine_version": "2.0.0",
        "build": "abc123def456",
        "authority": "https://app.upyoke.com/api/orgs/acme",
        "identity_verified": True,
        "actor": {"id": 7, "label": "status-actor"},
        "token_name": "status-token",
    }


def test_status_https_rejects_health_only_authority(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = status_config(tmp_path, repo)
    stub_server(monkeypatch, {"engine_version": "2.0.0"})

    def refuse_identity(*_args, **_kwargs):
        raise server_connect.ServerIdentityError(
            "token verification failed: HTTP 401"
        )

    monkeypatch.setattr(server_connect, "verify_server_identity", refuse_identity)
    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 1
    rendered = capsys.readouterr().out
    assert "secret-token" not in rendered
    report = json.loads(rendered)
    assert report["ok"] is False
    assert report["server"]["reachable"] is True
    assert report["server"]["identity_verified"] is False
    assert "server_identity_unverified" in {
        issue["code"] for issue in report["issues"]
    }


def test_status_self_hosted_loopback_uses_same_identity_proof(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = status_config(tmp_path, repo)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connections"]["prod"]["api_url"] = "http://127.0.0.1:8765"
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    stub_server(monkeypatch, {"engine_version": "2.0.0"})

    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["server"]["authority"] == "http://127.0.0.1:8765"
    assert report["server"]["identity_verified"] is True


def test_status_local_postgres_does_not_probe_http_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    def refuse_resolution(*_args, **_kwargs):
        raise AssertionError("local Postgres must not resolve an HTTPS credential")

    monkeypatch.setattr(
        https_transport,
        "resolve_https_connection",
        refuse_resolution,
    )
    report = status_server.server_status(
        {"transport": "local-postgres"},
        config_path=tmp_path / "config.json",
        explicit_env=None,
        check_reachability=True,
    )

    assert report["relevant"] is False
    assert report["identity_verified"] is None


def test_status_https_degrades_when_server_unreachable(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = status_config(tmp_path, repo)
    stub_server(monkeypatch, None)

    rc = yoke_operations_cli.main([
        "status", "--config", str(config), "--repo-root", str(repo), "--json",
    ])

    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["server"]["reachable"] is False
    assert report["server"]["engine_version"] == ""
    assert "server_unreachable" in {issue["code"] for issue in report["issues"]}


def test_render_human_shows_authenticated_server_authority() -> None:
    reachable = status_render.render_human(
        {"server": {
            "relevant": True,
            "reachable": True,
            "engine_version": "2.0.0",
            "authority": "https://app.upyoke.com/api/orgs/acme",
            "identity_verified": True,
            "actor": {"id": 7, "label": "status-actor"},
        }},
    )
    unreachable = status_render.render_human(
        {"server": {"relevant": True, "reachable": False}},
    )
    local_only = status_render.render_human(
        {"server": {"relevant": False, "reachable": None}},
    )

    assert (
        "  server: engine=2.0.0 "
        "authority=https://app.upyoke.com/api/orgs/acme identity=status-actor"
    ) in reachable
    assert "  server: unreachable (engine version unknown)" in unreachable
    assert "server:" not in local_only
