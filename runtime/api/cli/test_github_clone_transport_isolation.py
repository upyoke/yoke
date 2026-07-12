"""Credential-free clone/probe validation and hostile-environment isolation."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import onboard_checkout_ownership
from yoke_cli.config import project_git_transport as transport


def _config_entries(env: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"])
        for index in range(int(env["GIT_CONFIG_COUNT"]))
    ]


def _assert_remote_auth_isolated(
    env: dict[str, str],
    *,
    token_expected: bool,
) -> None:
    entries = _config_entries(env)
    assert ("credential.helper", "") in entries
    assert ("credential.https://github.com.helper", "") in entries
    assert ("http.extraHeader", "") in entries
    exact = [
        value for key, value in entries if key == "http.https://github.com/.extraheader"
    ]
    assert exact[0] == ""
    assert bool(exact[-1]) is token_expected


def test_credential_bearing_clone_url_never_launches_git_or_leaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launches: list[list[str]] = []
    monkeypatch.setattr(
        clone,
        "run_network_git",
        lambda command, **kwargs: launches.append(command),
    )
    hostile = "https://user:credential-sentinel@github.com/acme/widgets.git?x=1#frag"

    with pytest.raises(clone.CloneAccessError) as caught:
        clone.clone_with_token_fallback(
            tmp_path,
            "widgets",
            hostile,
            token=None,
        )

    assert launches == []
    assert "credential-sentinel" not in str(caught.value)
    assert hostile not in str(caught.value)
    assert "credential-free HTTPS" in str(caught.value)


def test_invalid_probe_reference_never_launches_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launches: list[list[str]] = []
    monkeypatch.setattr(
        transport,
        "run_network_git",
        lambda command, **kwargs: launches.append(command),
    )
    hostile = "https://user:credential-sentinel@github.com/acme/widgets.git"

    assert transport.remote_default_branch(hostile) is None
    assert transport.remote_is_reachable(hostile) is False
    assert launches == []


def test_scp_reference_is_normalized_before_clone_child_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)

    outcome = clone.clone_with_token_fallback(
        tmp_path,
        "widgets",
        "git@github.com:acme/widgets.git",
        token=None,
    )

    clean = "https://github.com/acme/widgets.git"
    assert seen["command"] == ["git", "clone", "--", clean, "."]
    assert outcome.origin_url == clean
    _assert_remote_auth_isolated(seen["env"], token_expected=False)


def test_failed_clone_never_removes_preexisting_dangling_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "widgets"
    target.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    monkeypatch.setattr(
        clone,
        "run_network_git",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            "",
            "repository not found",
        ),
    )

    with pytest.raises(clone.CloneAccessError):
        clone.clone_with_token_fallback(
            tmp_path,
            "widgets",
            "https://github.com/acme/widgets.git",
            token=None,
        )

    assert target.is_symlink()


def test_failed_clone_preserves_path_replaced_during_child_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "widgets"
    original = tmp_path / "widgets-original"

    def replace_target(command, **kwargs):
        assert os.fstat(kwargs["cwd_fd"])[:2] == target.stat()[:2]
        assert kwargs["pass_fds"]
        target.rename(original)
        target.mkdir()
        (target / "user-marker").write_text("keep", encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, "", "repository not found")

    monkeypatch.setattr(clone, "run_network_git", replace_target)
    with pytest.raises(clone.CloneAccessError, match="left untouched"):
        clone.clone_with_token_fallback(
            tmp_path,
            "widgets",
            "https://github.com/acme/widgets.git",
            token=None,
        )

    assert (target / "user-marker").read_text(encoding="utf-8") == "keep"
    assert original.is_dir()


def test_existing_option_shaped_clone_target_is_never_a_git_argument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "--help"
    target.mkdir()
    seen: list[list[str]] = []
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        seen.append(command)
        assert os.fstat(kwargs["cwd_fd"])[:2] == target.stat()[:2]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)

    clone.clone_with_token_fallback(
        tmp_path,
        "--help",
        "https://github.com/acme/widgets.git",
        token=None,
    )

    assert seen == [
        [
            "git",
            "clone",
            "--",
            "https://github.com/acme/widgets.git",
            ".",
        ]
    ]


def test_anonymous_failure_then_lazy_token_retry_never_invokes_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[list[tuple[str, str]]] = []
    helper_sentinel: list[str] = []
    provider_calls: list[str] = []
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        entries = _config_entries(kwargs["env"])
        attempts.append(entries)
        if ("credential.helper", "") not in entries:
            helper_sentinel.append("general")
        if ("credential.https://github.com.helper", "") not in entries:
            helper_sentinel.append("origin")
        if len(attempts) == 1:
            return subprocess.CompletedProcess(
                command,
                1,
                "",
                "fatal: authentication failed",
            )
        os.mkdir(".git", dir_fd=kwargs["cwd_fd"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)
    monkeypatch.setattr(clone, "run_git", lambda *args, **kwargs: None)

    outcome = clone.clone_with_token_fallback(
        tmp_path,
        "widgets",
        "https://github.com/acme/widgets.git",
        token=None,
        token_provider=lambda: provider_calls.append("provider") or "ghu_token",
    )

    assert outcome.used_token is True
    assert provider_calls == ["provider"]
    assert helper_sentinel == []
    assert len(attempts) == 2
    _assert_remote_auth_isolated(
        transport.git_config_env(tuple(f"{key}={value}" for key, value in attempts[0])),
        token_expected=False,
    )
    token_exact = [
        value
        for key, value in attempts[1]
        if key == "http.https://github.com/acme/widgets.git.extraheader"
    ]
    assert token_exact[-1].startswith("AUTHORIZATION: basic ")
    assert onboard_checkout_ownership.capture(tmp_path / "widgets") is not None


def test_preexisting_empty_clone_target_is_never_marked_owned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "widgets"
    target.mkdir()
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        os.mkdir(".git", dir_fd=kwargs["cwd_fd"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)

    clone.clone_with_token_fallback(
        tmp_path,
        "widgets",
        "https://github.com/acme/widgets.git",
        token=None,
    )

    assert onboard_checkout_ownership.capture(target) is None


def test_anonymous_success_does_not_resolve_lazy_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_calls: list[str] = []
    helper_sentinel: list[str] = []
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        entries = _config_entries(kwargs["env"])
        if ("credential.helper", "") not in entries:
            helper_sentinel.append("helper")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)

    clone.clone_with_token_fallback(
        tmp_path,
        "widgets",
        "https://github.com/acme/widgets.git",
        token=None,
        token_provider=lambda: provider_calls.append("provider") or "ghu_token",
    )

    assert provider_calls == []
    assert helper_sentinel == []


def test_probe_is_anonymous_and_helper_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments: list[dict[str, str]] = []
    monkeypatch.setattr(
        transport.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        environments.append(kwargs["env"])
        stdout = "ref: refs/heads/main\tHEAD\n" if "--symref" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(transport, "run_network_git", run)

    assert transport.remote_default_branch("git@github.com:acme/widgets.git") == "main"
    assert transport.remote_is_reachable("https://github.com/acme/widgets.git") is True
    assert len(environments) == 2
    for env in environments:
        _assert_remote_auth_isolated(env, token_expected=False)
