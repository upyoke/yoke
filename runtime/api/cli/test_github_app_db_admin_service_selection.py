"""An owner-only admin connection proves GitHub through the plane it administers.

`prod-db-admin` reaches the same universe as `prod` over a different
transport. The machine App binding belongs to that universe's https plane,
so a connection selection made under the admin label names that plane —
the merge child, `yoke github status`, and a default token read all resolve
through the one selector and prove the one binding.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.cli.test_github_status_merge_path_binding import (
    ADMIN_ENV,
    SERVICE_API_URL,
    _admin_sibling_machine,
)
from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


def test_admin_connection_selects_the_https_plane_it_administers(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _admin_sibling_machine(tmp_path, monkeypatch)
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)

    assert github_app_public_profile.selected_https_service_api_url(config) == (
        SERVICE_API_URL
    )
    selection = merge_path_binding.resolve_selection(config)
    assert selection.resolved is True
    assert selection.service_api_url == SERVICE_API_URL
    assert selection.local_connection_selected is False


def test_admin_connection_without_an_https_sibling_stays_local(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _admin_sibling_machine(tmp_path, monkeypatch)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connections"]["local-db-admin"] = {
        "transport": "local-postgres",
        "credential_source": {
            "kind": "dsn_file", "path": str(config.parent / "local.dsn"),
        },
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    config.chmod(0o600)
    monkeypatch.setenv(ENV_OVERRIDE, "local-db-admin")

    assert github_app_public_profile.selected_https_service_api_url(config) is None
    selection = merge_path_binding.resolve_selection(config)
    assert selection.service_api_url is None
    assert selection.local_connection_selected is True


def test_default_token_read_threads_the_selected_plane_to_the_credential_store(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _admin_sibling_machine(tmp_path, monkeypatch)
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)
    seen: dict[str, dict[str, Any]] = {}

    @contextmanager
    def unlocked(_path):
        yield

    def prove(_github, **kwargs):
        seen["profile"] = kwargs
        return SimpleNamespace()

    def refresh(**kwargs):
        seen["token"] = kwargs
        return SimpleNamespace(access_token="transient-user-token")

    monkeypatch.setattr(
        github_local_user_access.github_machine_operation, "operation_lock", unlocked,
    )
    monkeypatch.setattr(
        github_local_user_access.github_app_public_profile,
        "resolve_selected_and_match",
        prove,
    )
    monkeypatch.setattr(
        github_local_user_access.github_user_tokens,
        "access_token_from_machine_config",
        refresh,
    )

    token = github_local_user_access.access_token(config)

    assert token.access_token == "transient-user-token"
    assert seen["profile"]["service_api_url"] == SERVICE_API_URL
    assert seen["profile"]["local_connection_selected"] is False
    assert seen["token"]["_expected_service_api_url"] == SERVICE_API_URL
    assert seen["token"]["_expected_local_connection"] is False
