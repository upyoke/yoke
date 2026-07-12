"""Independent issue composition in machine GitHub status reports."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_security import (
    _configured_machine,
    _profile_opener,
    _refresh_opener,
)
from yoke_cli.config import github_git_credentials, github_machine


def _fail_helper_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github_git_credentials,
        "refresh_installed_helper",
        lambda: (_ for _ in ()).throw(OSError("read-only package site")),
    )


def test_status_marks_live_failure_as_cached_and_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    _fail_helper_refresh(monkeypatch)

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    report = github_machine.status(
        config_path=config,
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        token_opener=_refresh_opener,
        api_opener=unavailable,
    )

    assert report["ok"] is False
    assert report["ready"] is False
    assert report["identity"]["checked"] is True
    assert report["identity"]["ok"] is False
    assert report["access"]["snapshot_source"] == "cached"
    assert report["access"]["repo_listing_ok"] is False
    assert report["access"]["org_listing_ok"] is False
    assert "github_git_helper_upgrade_pending" in {
        item["code"] for item in report["issues"]
    }


def test_status_keeps_helper_warning_when_token_refresh_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    _fail_helper_refresh(monkeypatch)

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    report = github_machine.status(
        config_path=config,
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        token_opener=unavailable,
    )

    assert {item["code"] for item in report["issues"]} >= {
        "github_user_token_unavailable",
        "github_git_helper_upgrade_pending",
    }


def test_offline_status_does_not_republish_the_helper_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        github_git_credentials,
        "refresh_installed_helper",
        lambda: calls.append("refresh") or True,
    )

    report = github_machine.status(config_path=config, check=False)

    assert report["identity"]["checked"] is False
    assert calls == []


def test_suspended_installation_is_not_misreported_as_missing_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["github"]["installations"][0]["suspended"] = True
    config.write_text(json.dumps(payload), encoding="utf-8")

    report = github_machine.status(config_path=config, check=False)
    codes = {item["code"] for item in report["issues"]}

    assert report["permissions"]["ok"] is True
    assert report["permissions"]["usable"] is False
    assert report["ready"] is False
    assert "github_app_installation_suspended" in codes
    assert "github_app_no_usable_installation" in codes
    assert "github_app_installation_permissions_incomplete" not in codes
