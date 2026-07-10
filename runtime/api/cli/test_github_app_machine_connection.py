from __future__ import annotations

import json
from pathlib import Path
import stat
from typing import Any

from yoke_cli.config import github_app_user_api, github_machine
from yoke_cli.config import writer
from yoke_contracts import github_app_installation_permissions


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _device_opener():
    responses = iter([
        {
            "device_code": "device-secret",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        },
        {
            "access_token": "access-secret",
            "expires_in": 28800,
            "refresh_token": "refresh-secret",
            "refresh_token_expires_in": 15552000,
            "scope": "",
        },
    ])
    return lambda request, timeout: _Response(next(responses))


def _permissions() -> dict[str, str]:
    return {
        item.key: item.access
        for item in github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSIONS
    }


def _api_opener(*, installed: bool):
    def open_request(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"})
        if "/user/installations?" in url:
            if not installed:
                return _Response({"total_count": 0, "installations": []})
            return _Response({
                "total_count": 1,
                "installations": [{
                    "id": 123,
                    "account": {
                        "id": 9,
                        "login": "octo-org",
                        "type": "Organization",
                    },
                    "repository_selection": "selected",
                    "permissions": _permissions(),
                    "suspended_at": None,
                }],
            })
        if "/user/installations/123/repositories?" in url:
            return _Response({
                "total_count": 1,
                "repositories": [{
                    "id": 456,
                    "full_name": "octo-org/app",
                    "default_branch": "main",
                }],
            })
        raise AssertionError(f"unexpected GitHub API request: {url}")

    return open_request


def test_connect_persists_auth_but_stays_pending_without_installation(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    opened: list[str] = []
    notices: list[dict[str, Any]] = []

    report = github_machine.connect(
        config_path=config,
        client_id="Iv1.local",
        app_slug="yoke-local",
        api_url="https://api.github.com",
        web_url="https://github.com",
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=False),
        browser_open=lambda url: opened.append(url) or False,
        notify=lambda event: notices.append(dict(event)),
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    assert report["ok"] is True
    assert report["ready"] is False
    assert report["state"] == "pending_installation"
    assert report["install_url"] == (
        "https://github.com/apps/yoke-local/installations/new"
    )
    assert opened == [
        "https://github.com/login/device",
        "https://github.com/apps/yoke-local/installations/new",
    ]
    assert notices[0]["user_code"] == "ABCD-EFGH"
    assert notices[-1]["install_url"] == report["install_url"]
    payload = json.loads(config.read_text(encoding="utf-8"))
    authorization = payload["github"]["authorization"]
    credential = Path(authorization["refresh_credential_ref"])
    assert credential.is_file()
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600
    document = json.loads(credential.read_text(encoding="utf-8"))
    assert document["access_token"] == "access-secret"
    assert document["refresh_token"] == "refresh-secret"
    assert "access-secret" not in config.read_text(encoding="utf-8")
    assert "refresh-secret" not in config.read_text(encoding="utf-8")


def test_connect_discovers_installation_repositories_and_permissions(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"

    opened: list[str] = []
    report = github_machine.connect(
        config_path=config,
        client_id="Iv1.local",
        app_slug="yoke-local",
        device_opener=_device_opener(),
        api_opener=_api_opener(installed=True),
        add_installation=True,
        browser_open=lambda url: opened.append(url) or True,
        sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    assert report["ok"] is True
    assert report["ready"] is True
    assert report["operation"] == "github.connect"
    assert report["state"] == "connected"
    assert report["identity"]["login"] == "octocat"
    assert report["access"]["owners"] == ["octo-org"]
    assert report["access"]["repos"] == ["octo-org/app"]
    assert report["permissions"]["ok"] is True
    assert report["install_url"].endswith("/apps/yoke-local/installations/new")
    assert report["state"] == "connected"
    assert opened[-1] == report["install_url"]


def test_status_uses_cached_access_and_disconnect_removes_only_local_auth(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config, client_id="Iv1.local", app_slug="yoke-local",
        device_opener=_device_opener(), api_opener=_api_opener(installed=True),
        browser_open=lambda url: True, sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )

    status = github_machine.status(
        config_path=config, api_opener=_api_opener(installed=True),
        token_opener=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cached access token should avoid refresh")
        ),
    )
    assert status["ok"] is True
    credential = Path(json.loads(config.read_text(encoding="utf-8"))[
        "github"
    ]["authorization"]["refresh_credential_ref"])
    lock_path = credential.with_name(credential.name + ".lock")

    disconnected = github_machine.disconnect(config_path=config)

    assert disconnected == {
        "ok": True,
        "operation": "github.disconnect",
        "configured": False,
        "config_path": str(config),
        "credential_removed": True,
        "github_app_uninstalled": False,
        "issues": [],
    }
    assert not credential.exists()
    assert lock_path.is_file()
    assert not config.exists()


def test_reconnect_config_failure_keeps_old_credential_and_cleans_new_one(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    github_machine.connect(
        config_path=config, client_id="Iv1.local", app_slug="yoke-local",
        device_opener=_device_opener(), api_opener=_api_opener(installed=True),
        browser_open=lambda url: True, sleep=lambda seconds: None,
        monotonic=lambda: 0,
    )
    original = json.loads(config.read_text(encoding="utf-8"))
    old_credential = Path(
        original["github"]["authorization"]["refresh_credential_ref"]
    )
    before = set(old_credential.parent.glob("github-app-user-*.json"))

    def fail_write(*args, **kwargs):
        raise writer.MachineConfigWriteError("simulated config write failure")

    monkeypatch.setattr(writer, "set_github", fail_write)
    try:
        github_machine.connect(
            config_path=config, client_id="Iv1.replacement",
            app_slug="yoke-replacement", device_opener=_device_opener(),
            api_opener=_api_opener(installed=True), browser_open=lambda url: True,
            sleep=lambda seconds: None, monotonic=lambda: 0,
        )
    except github_machine.GitHubMachineError as exc:
        assert "simulated config write failure" in str(exc)
    else:
        raise AssertionError("expected config write failure")

    assert old_credential.is_file()
    assert json.loads(config.read_text(encoding="utf-8")) == original
    assert set(old_credential.parent.glob("github-app-user-*.json")) == before


def test_installation_discovery_has_a_pagination_safety_cap() -> None:
    installation = {
        "id": 123,
        "account": {"id": 9, "login": "octo-org", "type": "Organization"},
        "repository_selection": "selected",
        "permissions": _permissions(),
        "suspended_at": None,
    }

    def endless_pages(request, timeout):
        if request.full_url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"})
        return _Response({"installations": [installation] * 100})

    try:
        github_app_user_api.discover_access(
            api_url="https://api.github.com",
            access_token="access-secret",
            opener=endless_pages,
        )
    except github_app_user_api.GitHubAppUserApiError as exc:
        assert "exceeded 100 pages" in str(exc)
    else:
        raise AssertionError("expected pagination cap")


def test_connect_rejects_mismatched_web_and_api_before_oauth(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    network_calls: list[str] = []

    try:
        github_machine.connect(
            config_path=tmp_path / "config.json",
            client_id="Iv1.local", app_slug="yoke-local",
            web_url="https://github.com",
            api_url="https://api.evil.example",
            device_opener=lambda request, timeout: network_calls.append(
                request.full_url
            ),
        )
    except github_machine.GitHubMachineError as exc:
        assert "canonical bases" in str(exc)
    else:
        raise AssertionError("expected mismatched endpoint rejection")
    assert network_calls == []


def test_discovery_skips_suspended_installation_and_keeps_healthy_repos() -> None:
    def opener(request, timeout):
        url = request.full_url
        if url.endswith("/user"):
            return _Response({"id": 42, "login": "octocat"})
        if "/user/installations?" in url:
            base = {
                "account": {"id": 9, "login": "octo-org", "type": "Organization"},
                "repository_selection": "selected", "permissions": _permissions(),
            }
            return _Response({"installations": [
                {**base, "id": 111, "suspended_at": "2026-01-01T00:00:00Z"},
                {**base, "id": 222, "suspended_at": None},
            ]})
        if "/installations/111/" in url:
            raise AssertionError("suspended installation must not list repositories")
        if "/installations/222/repositories?" in url:
            return _Response({"repositories": [{
                "id": 456, "full_name": "octo-org/app", "default_branch": "main",
            }]})
        raise AssertionError(url)

    snapshot = github_app_user_api.discover_access(
        api_url="https://api.github.com", access_token="access", opener=opener,
    )

    assert [item["installation_id"] for item in snapshot["installations"]] == [111, 222]
    assert snapshot["installations"][0]["suspended"] is True
    assert [item["full_name"] for item in snapshot["repositories"]] == ["octo-org/app"]
