from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys
from contextlib import contextmanager

import pytest

from yoke_cli.config import github_git_credential_launcher
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_machine_operation
from yoke_cli.config import github_machine_state
from yoke_cli.config import github_user_tokens
from yoke_cli.config import writer
from yoke_cli.config import writer_github
from yoke_contracts.machine_config import schema as contract


def _credential(path: Path, label: str) -> None:
    github_git_credential_store.write_credential_document(path, {
        "schema_version": 2,
        "refresh_token": f"refresh-{label}",
        "refresh_expires_at": "2099-12-09T17:00:00+00:00",
    })


def _config(path: Path, credential_ref: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": contract.DEFAULT_GITHUB_API_URL,
            "web_url": contract.DEFAULT_GITHUB_WEB_URL,
            "app_slug": "yoke",
            "app_id": 123,
            "client_id": "Iv1.local",
            "authorization": {
                "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
                "refresh_credential_ref": str(credential_ref),
                "status": "authorized",
            },
        },
    }), encoding="utf-8")


def _base_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "active_env": "local",
        "connections": {
            "local": {
                "transport": "local-postgres",
                "prod": False,
                "credential_source": {
                    "kind": "dsn_file",
                    "path": str(path.parent / "local.dsn"),
                },
            },
        },
    }), encoding="utf-8")


def _github_entry(credential_ref: Path) -> dict:
    return {
        "api_url": contract.DEFAULT_GITHUB_API_URL,
        "web_url": contract.DEFAULT_GITHUB_WEB_URL,
        "app_slug": "yoke",
        "app_id": 123,
        "client_id": "Iv1.local",
        "profile_source": contract.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "refresh_credential_ref": str(credential_ref),
            "status": "authorized",
        },
    }


def test_cleanup_protects_crash_tombstone_still_referenced_by_config(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    live = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    _credential(live, "live")
    config = home / "config.json"
    _config(config, live)
    tombstone = github_machine_state.quarantine_owned_credential(live)
    assert tombstone is not None

    removed, failed = github_machine_state.cleanup_quarantined_credentials(config)

    assert (removed, failed) == (0, 0)
    assert tombstone.is_file()
    assert not live.exists()


def test_cleanup_never_infers_live_credential_is_orphaned_from_one_config(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    current = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    orphan = home / "secrets" / f"github-app-user-{'b' * 32}.json"
    _credential(current, "current")
    _credential(orphan, "orphan")
    config = home / "config.json"
    _config(config, current)

    removed, failed = github_machine_state.cleanup_quarantined_credentials(config)

    assert (removed, failed) == (0, 0)
    assert current.is_file()
    assert orphan.is_file()


def test_cleanup_for_one_config_preserves_another_configs_live_credential(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    first = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    second = home / "secrets" / f"github-app-user-{'b' * 32}.json"
    _credential(first, "first")
    _credential(second, "second")
    first_config = tmp_path / "first-config.json"
    second_config = tmp_path / "second-config.json"
    _config(first_config, first)
    _config(second_config, second)

    github_machine_state.cleanup_quarantined_credentials(first_config)

    assert first.is_file()
    assert second.is_file()


def test_two_configs_share_refresh_and_disconnect_without_cross_deletion(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    first_config = tmp_path / "first" / "config.json"
    second_config = tmp_path / "second" / "config.json"
    _base_config(first_config)
    _base_config(second_config)
    shared = home / "secrets" / f"github-app-user-{'c' * 32}.json"
    github_user_tokens.store_initial_token(
        shared,
        {
            "access_token": "access-initial",
            "expires_in": 28800,
            "refresh_token": "refresh-initial",
            "refresh_token_expires_in": 15552000,
        },
        device_flow_completed=True,
        config_path=first_config,
    )
    github = _github_entry(shared)
    writer.set_github(github, expected_credential_ref="", path=first_config)
    writer.set_github(github, expected_credential_ref="", path=second_config)

    first_clear = writer.clear_github(
        expected_credential_ref=str(shared), path=first_config,
    )

    assert shared.is_file()
    assert first_clear["credential_cleanup"]["shared"] is True

    class _Response:
        def __init__(self, request) -> None:
            self.url = request.full_url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self) -> str:
            return self.url

        def read(self, size: int = -1) -> bytes:
            body = json.dumps({
                "access_token": "access-refreshed",
                "expires_in": 28800,
                "refresh_token": "refresh-rotated",
                "refresh_token_expires_in": 15552000,
            }).encode("utf-8")
            return body[:size] if size >= 0 else body

    result = github_git_credential_store.access_token_from_machine_config(
        second_config,
        opener=lambda request, timeout: _Response(request),
    )
    document = github_git_credential_store.read_credential_document(shared)
    assert result["access_token"] == "access-refreshed"
    assert document["config_owners"] == [str(second_config.resolve())]
    assert document["config_ownership_complete"] is True

    second_clear = writer.clear_github(
        expected_credential_ref=str(shared), path=second_config,
    )
    assert second_clear["credential_cleanup"]["removed"] is True
    assert not shared.exists()


def test_machine_operation_lock_is_global_across_config_parents(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    targets: list[Path] = []

    @contextmanager
    def record_lock(path):
        targets.append(Path(path))
        yield

    monkeypatch.setattr(
        github_machine_operation.github_git_credential_file,
        "exclusive_lock",
        record_lock,
    )
    with github_machine_operation.operation_lock(tmp_path / "one" / "config.json"):
        pass
    with github_machine_operation.operation_lock(tmp_path / "two" / "config.json"):
        pass

    assert targets == [
        home / "secrets" / ".github-machine-operation",
        home / "secrets" / ".github-machine-operation",
    ]


def test_interruption_after_config_commit_leaves_recoverable_old_credential(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    _base_config(config)
    old = home / "secrets" / f"github-app-user-{'d' * 32}.json"
    new = home / "secrets" / f"github-app-user-{'e' * 32}.json"
    for path, label in ((old, "old"), (new, "new")):
        github_user_tokens.store_initial_token(
            path,
            {
                "access_token": f"access-{label}",
                "expires_in": 28800,
                "refresh_token": f"refresh-{label}",
                "refresh_token_expires_in": 15552000,
            },
            device_flow_completed=True,
            config_path=config,
        )
    writer.set_github(
        _github_entry(old), expected_credential_ref="", path=config,
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            writer_github,
            "_release_owned_credential",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                KeyboardInterrupt()
            ),
        )
        with pytest.raises(KeyboardInterrupt):
            writer.set_github(
                _github_entry(new),
                expected_credential_ref=str(old),
                path=config,
            )

    assert json.loads(config.read_text(encoding="utf-8"))["github"][
        "authorization"
    ]["refresh_credential_ref"] == str(new)
    assert old.is_file() and new.is_file()
    removed, failed = github_machine_state.cleanup_quarantined_credentials(config)
    assert (removed, failed) == (1, 0)
    assert not old.exists()
    assert new.is_file()


def test_cleanup_fails_closed_when_machine_config_is_unreadable(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    orphan = home / "secrets" / f"github-app-user-{'b' * 32}.json"
    _credential(orphan, "orphan")
    config = home / "config.json"
    config.write_text("{not-json", encoding="utf-8")

    assert github_machine_state.cleanup_quarantined_credentials(config) == (0, 0)
    assert orphan.is_file()


def _helper_command(python: Path, helper: Path, config: Path) -> str:
    return "!" + " ".join(
        shlex.quote(str(value))
        for value in (python, helper, "--config", config)
    )


def test_prior_runtime_helper_requires_valid_adjacent_bundle(
    tmp_path, monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    site = tmp_path / "prior-site"
    helper = github_git_credentials.install_stable_helper(site)
    current_site = tmp_path / "current-site"
    monkeypatch.setattr(
        github_git_credentials, "_helper_site_dir", lambda: current_site,
    )

    assert github_git_credentials._is_yoke_helper(
        _helper_command(Path(sys.executable), helper, config),
        config_path=config,
    )


def test_active_group_writable_runtime_recognizes_prior_helper_bundle(
    tmp_path, monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    site = tmp_path / "prior-site"
    helper = github_git_credentials.install_stable_helper(site)
    active_python = tmp_path / "active-python"
    active_python.write_text("#!/bin/sh\n", encoding="utf-8")
    active_python.chmod(0o775)
    monkeypatch.setattr(
        github_git_credentials.sys, "executable", str(active_python),
    )
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_site_dir",
        lambda: tmp_path / "current-site",
    )

    assert github_git_credentials._is_yoke_helper(
        _helper_command(active_python, helper, config),
        config_path=config,
    )


def test_group_writable_prior_runtime_is_not_recognized(
    tmp_path, monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    site = tmp_path / "prior-site"
    helper = github_git_credentials.install_stable_helper(site)
    active_python = tmp_path / "active-python"
    active_python.write_text("#!/bin/sh\n", encoding="utf-8")
    active_python.chmod(0o755)
    prior_python = tmp_path / "prior-python"
    prior_python.write_text("#!/bin/sh\n", encoding="utf-8")
    prior_python.chmod(0o775)
    monkeypatch.setattr(
        github_git_credentials.sys, "executable", str(active_python),
    )
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_site_dir",
        lambda: tmp_path / "current-site",
    )

    assert not github_git_credentials._is_yoke_helper(
        _helper_command(prior_python, helper, config),
        config_path=config,
    )


def test_marker_shaped_helper_without_bundle_is_preserved(
    tmp_path, monkeypatch,
) -> None:
    config = tmp_path / "config.json"
    site = tmp_path / "lookalike-site"
    site.mkdir()
    helper = site / github_git_credentials.STABLE_HELPER_FILE_NAME
    helper.write_bytes(Path(github_git_credential_launcher.__file__).read_bytes())
    helper.chmod(0o644)
    monkeypatch.setattr(
        github_git_credentials,
        "_helper_site_dir",
        lambda: tmp_path / "current-site",
    )

    assert not github_git_credentials._is_yoke_helper(
        _helper_command(Path(sys.executable), helper, config),
        config_path=config,
    )
