"""Machine GitHub operation-lock OS failures remain typed at public surfaces."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from yoke_cli.config import github_binding_auth, github_machine
from yoke_cli.config import github_git_credential_file as credential_file
from yoke_cli.config import github_git_credential_helper


def test_connect_wraps_operation_lock_parent_creation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mkdir = credential_file.Path.mkdir

    def fail_secrets_parent(path, *args, **kwargs):
        if path.name == "secrets":
            raise OSError("raw mkdir detail")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(credential_file.Path, "mkdir", fail_secrets_parent)
    with pytest.raises(github_machine.GitHubMachineError) as caught:
        github_machine.connect(config_path=tmp_path / "config.json")

    assert "operation lock is unavailable" in str(caught.value)
    assert "raw mkdir detail" not in str(caught.value)


def test_status_wraps_operation_lock_open_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credential_file.os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("raw open detail")
        ),
    )
    with pytest.raises(github_machine.GitHubMachineError) as caught:
        github_machine.status(config_path=tmp_path / "config.json")

    assert "operation lock is unavailable" in str(caught.value)
    assert "raw open detail" not in str(caught.value)


def test_binding_wraps_operation_lock_flock_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        credential_file.fcntl,
        "flock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("raw flock detail")
        ),
    )
    with pytest.raises(github_binding_auth.GitHubBindingAuthError) as caught:
        github_binding_auth.profile_bound_access_for_binding(
            tmp_path / "config.json",
        )

    assert "operation lock is unavailable" in str(caught.value)
    assert "raw flock detail" not in str(caught.value)


def test_git_helper_turns_operation_lock_fchmod_failure_into_safe_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        credential_file.os,
        "fchmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("raw chmod detail")
        ),
    )
    result = github_git_credential_helper.main(
        ["--config", str(tmp_path / "config.json"), "get"],
        stdin=io.StringIO("protocol=https\nhost=github.com\n\n"),
        stdout=io.StringIO(),
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "credential unavailable" in error
    assert "raw chmod detail" not in error
