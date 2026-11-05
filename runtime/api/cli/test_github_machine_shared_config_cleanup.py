"""Shared machine credentials remain owned across two configs in one home."""

import json
from pathlib import Path
from contextlib import contextmanager

from runtime.api.cli.github_machine_credential_cleanup_test_support import (
    _base_config,
    _github_entry,
)
from yoke_cli.config import (
    github_git_credential_store,
    github_user_tokens,
    writer,
    github_machine_operation,
)


def test_two_configs_share_refresh_and_disconnect_without_cross_deletion(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    first_config = home / "first" / "config.json"
    second_config = home / "second" / "config.json"
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
        expected_credential_ref=str(shared),
        path=first_config,
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
            body = json.dumps(
                {
                    "access_token": "access-refreshed",
                    "expires_in": 28800,
                    "refresh_token": "refresh-rotated",
                    "refresh_token_expires_in": 15552000,
                }
            ).encode("utf-8")
            return body[:size] if size >= 0 else body

    result = github_git_credential_store.access_token_from_machine_config(
        second_config,
        opener=lambda request, timeout: _Response(request),
    )
    document = github_git_credential_store.read_credential_document(shared)
    assert (result["access_token"], result["cached"]) == ("access-initial", True)
    assert document["config_owners"] == [str(second_config.resolve())]
    assert document["config_ownership_complete"] is True

    second_clear = writer.clear_github(
        expected_credential_ref=str(shared),
        path=second_config,
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
