"""The connected-credential clone checks out only a remote that has commits."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_clone_support as clone


@pytest.mark.parametrize(("has_commit", "checkout"), [(True, ["-f"]), (False, [])])
def test_connected_token_clones_once_and_rehomes_origin_cleanly(
    tmp_path: Path, monkeypatch, has_commit: bool, checkout: list[str]
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    token = "ghs_secret_token_value"
    calls: list[dict] = []
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: (
            calls.append(kwargs) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )
    cleaned: list[str] = []
    monkeypatch.setattr(
        clone,
        "run_git",
        lambda _root, *_args: cleaned.append(_args[-1]),
    )
    # An empty remote leaves HEAD unborn, so there is nothing to check out.
    monkeypatch.setattr(clone.project_local_git, "has_commit", lambda _root: has_commit)

    outcome = clone.clone_with_connected_access(
        parent,
        "widgets",
        "git@github.com:acme/widgets.git",
        token=token,
    )

    # The credential the caller already established reads the repo directly —
    # a private source never pays for a guaranteed anonymous failure first.
    assert outcome.used_token is True
    assert outcome.origin_url == "https://github.com/acme/widgets.git"
    assert [
        {key: value for key, value in call.items() if key != "target_claim"}
        for call in calls
    ] == [{"token": token, "github_web_url": None}]
    assert cleaned == ["https://github.com/acme/widgets.git", *checkout]


def test_private_source_resolves_the_lazy_credential_before_cloning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent = tmp_path / "checkouts"
    parent.mkdir()
    attempts: list[dict] = []
    monkeypatch.setattr(
        clone,
        "_run_clone",
        lambda *args, **kwargs: (
            attempts.append(kwargs) or subprocess.CompletedProcess([], 0, "", "")
        ),
    )
    monkeypatch.setattr(clone, "run_git", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clone.project_local_git, "has_commit", lambda _root: True)

    outcome = clone.clone_with_connected_access(
        parent,
        "widgets",
        "https://github.com/acme/widgets.git",
        token_provider=lambda: "ghu_private",
    )

    assert outcome.used_token is True
    assert len(attempts) == 1
    assert attempts[0]["token"] == "ghu_private"
