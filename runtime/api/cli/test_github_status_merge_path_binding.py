"""Machine GitHub status proves the binding a local merge authorizes through."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import urllib.error

import pytest

from runtime.api.cli.test_github_app_machine_connection import _api_opener
from runtime.api.cli.test_github_app_machine_security import (
    _configured_machine,
    _profile_opener,
    _refresh_opener,
)
from yoke_cli.commands import merge_item_local_runtime as local_runtime
from yoke_cli.commands.adapters import github as github_adapter
from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_machine
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_core.domain.github_app_dispatch_context import LOCAL_USER_TOKEN_PROVIDER


SERVICE_API_URL = "https://api.upyoke.com"
ADMIN_ENV = "prod-db-admin"


def _connected_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A valid stored grant on a machine whose active connection is HTTPS."""

    config, _credential = _configured_machine(tmp_path, monkeypatch)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    payload = json.loads(config.read_text(encoding="utf-8"))
    token_file = config.parent / "service-token"
    token_file.write_text("service-token\n", encoding="utf-8")
    payload["active_env"] = "prod"
    payload["connections"] = {
        "prod": {
            "transport": "https",
            "api_url": SERVICE_API_URL,
            "credential_source": {"kind": "token_file", "path": str(token_file)},
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    return config


def _admin_sibling_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A connected machine whose https plane has an owner-only admin sibling."""

    config = _connected_machine(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connections"][ADMIN_ENV] = {
        "transport": "local-postgres",
        "prod": True,
        "credential_source": {
            "kind": "dsn_file", "path": str(config.parent / "prod.dsn"),
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    return config


def _status(config: Path, **kwargs: Any) -> dict[str, Any]:
    """Check status the way the `yoke github status` command checks it."""

    return github_machine.status(
        config_path=config,
        **merge_path_binding.status_connection_scope(config),
        **kwargs,
    )


def test_status_command_pins_the_connection_a_merge_authorizes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)
    seen: dict[str, Any] = {}

    def capture(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(github_adapter.github_machine, "status", capture)

    assert github_adapter.github_status(["--config", str(config), "--json"]) == 0
    assert seen["service_api_url"] == SERVICE_API_URL
    assert seen["local_connection_selected"] is False


def test_merge_reads_the_user_token_through_the_selection_status_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)
    reads: list[dict[str, Any]] = []

    def token_loader(**kwargs: Any) -> SimpleNamespace:
        reads.append(kwargs)
        return SimpleNamespace(access_token="transient-user-token")

    monkeypatch.setattr(github_local_user_access, "access_token", token_loader)

    with local_runtime.machine_github_user_authority():
        provider = LOCAL_USER_TOKEN_PROVIDER.get()
        assert provider is not None
        assert provider() == "transient-user-token"

    assert reads == [merge_path_binding.status_connection_scope(config)]


def test_a_refused_token_read_reports_the_merge_binding_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)

    def refused(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 400, "Bad Request", hdrs=None, fp=None,
        )

    report = _status(config, profile_opener=_profile_opener, token_opener=refused)
    binding = report["bindings"]["user_authorization"]

    assert binding["verdict"] == merge_path_binding.VERDICT_BROKEN
    assert "yoke github connect" in binding["hint"]
    assert report["ok"] is False
    assert report["ready"] is False


def test_a_contended_token_read_reports_the_merge_binding_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)

    def unavailable(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "Unavailable", hdrs=None, fp=None,
        )

    report = _status(config, profile_opener=_profile_opener, token_opener=unavailable)
    binding = report["bindings"]["user_authorization"]

    assert binding["verdict"] == merge_path_binding.VERDICT_BUSY
    assert "yoke github connect" not in binding["hint"]
    assert "retry the command" in binding["hint"]
    assert report["ready"] is False


def test_offline_status_reports_an_unproven_merge_path_and_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)

    report = github_machine.status(config_path=config, check=False)
    verdicts = {
        name: report["bindings"][name]["verdict"]
        for name in merge_path_binding.READINESS_BINDINGS
    }

    assert verdicts == {
        "user_authorization": merge_path_binding.VERDICT_UNPROVEN,
        "app_installation": merge_path_binding.VERDICT_UNPROVEN,
    }
    assert report["ok"] is True
    assert report["ready"] is False


def test_a_proven_machine_reports_both_bindings_ok_and_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _connected_machine(tmp_path, monkeypatch)

    report = _status(
        config,
        profile_opener=_profile_opener,
        token_opener=_refresh_opener,
        api_opener=_api_opener(installed=True),
    )
    verdicts = {
        name: report["bindings"][name]["verdict"]
        for name in merge_path_binding.READINESS_BINDINGS
    }

    assert verdicts == {
        "user_authorization": merge_path_binding.VERDICT_OK,
        "app_installation": merge_path_binding.VERDICT_OK,
    }
    assert report["ok"] is True
    assert report["ready"] is True
    assert "user authorization (merge path): ok" in github_machine.render_human(report)


def test_status_under_the_admin_connection_proves_the_plane_it_administers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _admin_sibling_machine(tmp_path, monkeypatch)
    monkeypatch.setenv("YOKE_ENV", ADMIN_ENV)

    assert merge_path_binding.status_connection_scope(config) == {
        "service_api_url": SERVICE_API_URL,
        "local_connection_selected": False,
    }

    report = _status(
        config,
        profile_opener=_profile_opener,
        token_opener=_refresh_opener,
        api_opener=_api_opener(installed=True),
    )
    verdicts = {
        name: report["bindings"][name]["verdict"]
        for name in merge_path_binding.READINESS_BINDINGS
    }

    assert verdicts == {
        "user_authorization": merge_path_binding.VERDICT_OK,
        "app_installation": merge_path_binding.VERDICT_OK,
    }
    assert report["ready"] is True
