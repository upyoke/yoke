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
from yoke_cli.config import github_git_credential_file as credential_file
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
    # The token read failed, so the merge path is broken and the App access
    # snapshot is only cached rather than disproven.
    assert report["bindings"]["user_authorization"]["verdict"] == "broken"
    assert report["bindings"]["app_installation"]["verdict"] == "unproven"
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

    def refused(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", hdrs=None, fp=None,
        )

    report = github_machine.status(
        config_path=config,
        service_api_url="https://api.upyoke.com",
        profile_opener=_profile_opener,
        token_opener=refused,
    )

    assert {item["code"] for item in report["issues"]} >= {
        "github_user_token_unavailable",
        "github_git_helper_upgrade_pending",
    }


def test_status_reports_an_unreachable_refresh_as_retryable_not_a_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)
    config.chmod(0o600)

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
    issues = {item["code"]: item for item in report["issues"]}

    assert report["ok"] is False
    assert "github_user_token_read_busy" in issues
    assert "github_user_token_unavailable" not in issues
    assert "yoke github connect" not in issues["github_user_token_read_busy"]["hint"]


def test_status_answers_a_contended_machine_lock_with_a_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _credential = _configured_machine(tmp_path, monkeypatch)

    def busy(*args, **kwargs):
        raise credential_file.CredentialFileBusy("held by another operation")

    monkeypatch.setattr(credential_file, "exclusive_lock", busy)

    with pytest.raises(github_machine.GitHubMachineError) as raised:
        github_machine.status(config_path=config, check=False)

    assert "holding the machine operation lock" in str(raised.value)
    assert "reconnect" not in str(raised.value).lower()


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


def test_offline_status_reports_the_access_token_a_push_would_carry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two halves of the credential are separately reportable.

    The refresh credential can read healthy while pushes fail, because a push
    presents the access token instead. Proving that half live would mean
    refreshing, which rotates the authorization and breaks a push in flight —
    so this reads the stored document and nothing else.
    """

    config, credential = _configured_machine(tmp_path, monkeypatch)
    document = json.loads(credential.read_text(encoding="utf-8"))
    document["access_token"] = "stored-access"
    document["expires_at"] = "2099-12-09T17:00:00+00:00"
    credential.write_text(json.dumps(document), encoding="utf-8")

    report = github_machine.status(config_path=config, check=False)
    binding = report["bindings"]["git_access_token"]

    assert binding["verdict"] == "ok"
    assert "2099-12-09T17:00:00+00:00" in binding["message"]


def test_a_machine_with_no_cached_token_is_reported_but_still_provable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cold cache is not a fault, so it never gates readiness."""

    config, _credential = _configured_machine(tmp_path, monkeypatch)

    report = github_machine.status(config_path=config, check=False)
    binding = report["bindings"]["git_access_token"]

    assert binding["verdict"] == "unproven"
    assert "no access token is stored yet" in binding["message"]
    assert report["ok"] is True
