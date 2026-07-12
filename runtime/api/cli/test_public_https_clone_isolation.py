"""Anonymous external HTTPS clone support under GitHub credential isolation."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import project_git_transport as transport
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _entries(env: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"])
        for index in range(int(env["GIT_CONFIG_COUNT"]))
    ]


def test_external_https_clone_stays_anonymous_and_preserves_clean_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "https://gitlab.com/acme/widgets.git"
    launches: list[tuple[list[str], dict[str, str]]] = []
    provider_calls: list[str] = []
    monkeypatch.setenv("HTTPS_PROXY", "https://hostile-proxy.invalid")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "!hostile-helper")
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def run(command, **kwargs):
        launches.append((command, kwargs["env"]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clone, "run_network_git", run)

    outcome = clone.clone_with_token_fallback(
        tmp_path,
        "widgets",
        remote,
        token_provider=lambda: provider_calls.append("called") or "ghu_secret",
    )

    assert outcome.origin_url == remote
    assert outcome.used_token is False
    assert provider_calls == []
    assert [command for command, _env in launches] == [
        ["git", "clone", "--", remote, "."],
    ]
    env = launches[0][1]
    entries = _entries(env)
    assert ("credential.helper", "") in entries
    assert ("credential.https://gitlab.com.helper", "") in entries
    assert ("http.extraHeader", "") in entries
    assert ("http.https://gitlab.com/.extraheader", "") in entries
    assert ("http.followRedirects", "false") in entries
    assert ("http.proxy", "") in entries
    assert (f"http.{remote}.followRedirects", "false") in entries
    assert (f"http.{remote}.proxy", "") in entries
    assert not any("AUTHORIZATION" in value for _key, value in entries)
    assert "HTTPS_PROXY" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_ALLOW_PROTOCOL"] == "https"


@pytest.mark.parametrize(
    "remote",
    [
        "http://gitlab.com/acme/widgets.git",
        "ssh://git@gitlab.com/acme/widgets.git",
        "git@gitlab.com:acme/widgets.git",
        "https://user:secret@gitlab.com/acme/widgets.git",
        "https://gitlab.com/acme/widgets.git?access_token=secret",
        "https://gitlab.com/acme/widgets.git#secret",
    ],
)
def test_external_clone_rejects_credentials_and_non_https_transports(
    remote: str,
) -> None:
    with pytest.raises(ProjectOnboardError, match="credential-free HTTPS"):
        transport.clean_remote_url(remote)


def test_configured_github_origin_mismatch_does_not_become_generic() -> None:
    with pytest.raises(ProjectOnboardError, match="configured GitHub"):
        transport.clean_remote_url(
            "https://github.com/acme/widgets.git",
            web_url="https://ghe.example",
        )


def test_failed_external_clone_never_resolves_or_sends_github_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = "https://gitlab.com/acme/widgets.git"
    launches: list[dict[str, str]] = []
    provider_calls: list[str] = []
    monkeypatch.setattr(
        clone.project_clone_runner.project_git_prerequisite,
        "require_git_available",
        lambda: None,
    )

    def fail(_command, **kwargs):
        launches.append(kwargs["env"])
        return subprocess.CompletedProcess(
            [], 1, "", "fatal: authentication failed",
        )

    monkeypatch.setattr(clone, "run_network_git", fail)

    with pytest.raises(clone.CloneAccessError) as caught:
        clone.clone_with_token_fallback(
            tmp_path,
            "widgets",
            remote,
            token_provider=(
                lambda: provider_calls.append("called") or "ghu_secret"
            ),
        )

    assert provider_calls == []
    assert len(launches) == 1
    assert remote in str(caught.value)
    assert "external HTTPS repositories" in str(caught.value)
    assert not any(
        "AUTHORIZATION" in value
        for _key, value in _entries(launches[0])
    )


def test_explicit_github_token_is_rejected_for_external_origin() -> None:
    with pytest.raises(ProjectOnboardError, match="outside the configured"):
        transport.isolated_remote_config(
            "https://gitlab.com/acme/widgets.git",
            token="ghu_never_send",
        )
