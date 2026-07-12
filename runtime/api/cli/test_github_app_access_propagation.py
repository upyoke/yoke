from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from typing import Any
import urllib.error

from runtime.api.cli.test_github_app_machine_connection import (
    _api_opener,
    _device_opener,
    _explicit_profile,
    _profile_opener,
)
from runtime.api.cli.test_github_app_machine_security import (
    _configured_machine,
    _empty_installation_opener,
    _refresh_opener,
)
from yoke_cli.config import github_machine, writer


def test_connect_retries_fresh_user_token_until_github_accepts_it(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    healthy = _api_opener(installed=True)
    user_attempts = 0
    sleep_calls: list[float] = []
    notices: list[dict[str, Any]] = []
    opened: list[str] = []

    def delayed_authorization(request, timeout):
        nonlocal user_attempts
        if request.full_url.endswith("/user"):
            user_attempts += 1
            assert request.get_header("Authorization") == "Bearer access-secret"
            if user_attempts < 3:
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", hdrs=None, fp=None,
                )
        return healthy(request, timeout)

    report = github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=delayed_authorization,
        browser_open=lambda url: opened.append(url) or True,
        notify=lambda event: notices.append(dict(event)),
        sleep=lambda seconds: sleep_calls.append(seconds),
        monotonic=lambda: 0,
    )

    assert report["ok"] is True
    assert report["ready"] is True
    assert report["identity"]["login"] == "octocat"
    assert report["access"]["repos"] == ["octo-org/app"]
    assert user_attempts == 3
    assert sleep_calls == [5, 1.0, 2.0]
    assert [
        event["attempt"] for event in notices
        if event["phase"] == "github_access_propagation_retry"
    ] == [2, 3]
    assert opened[0] == "https://github.com/login/device"
    assert "access-secret" not in github_machine.dumps_json(report)


def test_connect_bounds_persistent_unauthorized_checks_without_secret_leak(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    user_attempts = 0
    sleep_calls: list[float] = []

    def unauthorized(request, timeout):
        nonlocal user_attempts
        user_attempts += 1
        body = json.dumps({
            "message": "Bad credentials for access-secret",
        }).encode("utf-8")
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs={"X-GitHub-Request-Id": "request-123"},
            fp=BytesIO(body),
        )

    report = github_machine.connect(
        config_path=config,
        **_explicit_profile(),
        device_opener=_device_opener(),
        api_opener=unauthorized,
        browser_open=lambda url: True,
        sleep=lambda seconds: sleep_calls.append(seconds),
        monotonic=lambda: 0,
    )

    rendered = github_machine.dumps_json(report)
    assert report["ok"] is False
    assert report["ready"] is False
    assert user_attempts == 4
    assert sleep_calls == [5, 1.0, 2.0, 4.0]
    assert "/user" in report["issues"][0]["message"]
    assert "request_id=request-123" in report["issues"][0]["message"]
    assert "message=Bad credentials for <redacted>" in report["issues"][0]["message"]
    assert "access-secret" not in rendered
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["github"]["authorization"]["status"] == "authorized"


def test_status_retries_transient_unauthorized_without_revoking(
    tmp_path: Path, monkeypatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    config.chmod(0o600)
    user_attempts = 0
    sleep_calls: list[float] = []

    def delayed_authorization(request, timeout):
        nonlocal user_attempts
        if request.full_url.endswith("/user"):
            user_attempts += 1
            if user_attempts == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", hdrs=None, fp=None,
                )
        return _empty_installation_opener(request, timeout)

    report = github_machine.status(
        config_path=config,
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        token_opener=_refresh_opener,
        api_opener=delayed_authorization,
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    assert report["ok"] is True
    assert report["identity"]["ok"] is True
    assert user_attempts == 2
    assert sleep_calls == [1.0]
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["github"]["authorization"]["status"] == "authorized"


def test_status_marks_revoked_only_after_unauthorized_retries_exhaust(
    tmp_path: Path, monkeypatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    config.chmod(0o600)
    attempts = 0
    sleep_calls: list[float] = []

    def revoked(request, timeout):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", hdrs=None, fp=None,
        )

    monkeypatch.setattr(
        writer,
        "set_github",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            writer.MachineConfigWriteError("read-only config")
        ),
    )

    report = github_machine.status(
        config_path=config,
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        token_opener=_refresh_opener,
        api_opener=revoked,
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    codes = {item["code"] for item in report["issues"]}
    assert attempts == 4
    assert sleep_calls == [1.0, 2.0, 4.0]
    assert "github_revoked_status_not_persisted" in codes
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["github"]["authorization"]["status"] == "authorized"
