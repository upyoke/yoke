"""Deletion scope for Yoke-owned GitHub App user credentials."""

from pathlib import Path

import pytest

from yoke_cli.config import github_git_credential_store, github_machine_state


@pytest.mark.parametrize(
    "relative_path",
    [
        "deployment-config.json",
        "github-app-user-not-a-generated-id.json",
        f"nested/github-app-user-{'b' * 32}.json",
    ],
)
def test_credential_cleanup_refuses_non_owned_files_inside_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    candidate = home / "secrets" / relative_path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text('{"important": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="not a Yoke-owned"):
        github_machine_state.remove_owned_credential(candidate)

    assert candidate.exists()


def test_credential_cleanup_removes_generated_owned_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    candidate = home / "secrets" / f"github-app-user-{'c' * 32}.json"
    github_git_credential_store.write_credential_document(candidate, {
        "schema_version": 1,
        "access_token": "access-secret",
        "expires_at": "2099-07-09T17:00:00+00:00",
        "refresh_token": "refresh-secret",
        "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        "scope": "",
        "token_type": "bearer",
    })

    assert github_machine_state.remove_owned_credential(candidate) is True
    assert not candidate.exists()
