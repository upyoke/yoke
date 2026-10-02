"""Optional Git credentials never replace stored Yoke authorization."""

import os
import subprocess
import time

import pytest

from runtime.api.cli.git_http_test_support import (
    authenticated_remote,
    git,
    own_credential_config,
)
from yoke_cli.config import credentialed_git as cg, project_git_process

ORIGIN = "https://github.com/example/repo.git"


@pytest.fixture
def no_authorization(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    for key, value in {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
        "YOKE_MACHINE_HOME": str(home / "yoke"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }.items():
        monkeypatch.setenv(key, value)
    for key in ("YOKE_MACHINE_CONFIG_FILE", "SSH_AUTH_SOCK", "YOKE_ENV"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(cg, "configured_web_url", lambda: "https://github.com")
    return home


@pytest.mark.parametrize("credential", [False, True])
def test_real_github_push_uses_optional_helper_or_fails_without_prompt(
    tmp_path, monkeypatch, no_authorization, credential
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-b", "main")
    git(checkout, "config", "user.name", "Fixture")
    git(checkout, "config", "user.email", "fixture@example.invalid")
    (checkout / "base").write_text("base\n")
    git(checkout, "add", ".")
    git(checkout, "commit", "-m", "base")
    with authenticated_remote(tmp_path) as (url, remote, requests):
        if credential:
            monkeypatch.setenv(
                "GIT_CONFIG_GLOBAL", str(own_credential_config(no_authorization, url))
            )
        rewrite = f"url.{url}.insteadOf={ORIGIN}"
        result = cg.run(
            ["-c", rewrite, "push", ORIGIN, "main"], cwd=str(checkout), timeout=5
        )
        if credential:
            assert result.returncode == 0, result.stderr
            assert git(remote, "rev-parse", "main") == git(
                checkout, "rev-parse", "HEAD"
            )
            assert result.credential_source == "pushed with your own git credentials"
            assert any(requests)
        else:
            assert result.returncode != 0
            assert "No Yoke GitHub authorization is stored" in result.stderr
            assert "your own git credentials did not work" in result.stderr
            assert "yoke github connect" in result.stderr
            assert not any(requests)


def test_absent_authorization_preserves_ssh_and_disables_prompts(no_authorization):
    with cg.git_environment(["push", "git@github.com:example/repo.git", "main"]) as env:
        assert env["HOME"] == str(no_authorization)
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GCM_INTERACTIVE"] == "Never"
        assert env["GIT_ASKPASS"] == env["SSH_ASKPASS"] == ""
        assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
        values = [
            env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))
        ]
        assert not any(
            "insteadOf" in key or "extraheader" in key or "helper" in key
            for key in values
        )


def test_stored_failure_never_runs_ambient_credentials(no_authorization, monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.github_config",
        lambda _path: {"authorization": {"status": "revoked"}},
    )
    monkeypatch.setattr(
        cg,
        "resolve_token",
        lambda _url: (_ for _ in ()).throw(
            cg.CredentialedGitError("stored auth revoked")
        ),
    )
    monkeypatch.setattr(
        cg, "_run_own_credentials", lambda *_a: pytest.fail("ambient auth must not run")
    )
    assert cg.run(["push", ORIGIN, "main"]).returncode == cg.REFUSAL_EXIT_CODE


def test_optional_helper_timeout_kills_the_child_group(no_authorization, monkeypatch):
    monkeypatch.setattr(
        "yoke_cli.config.repo_upstream_git.network_timeout_seconds", lambda: 0.1
    )
    original = project_git_process.run_network_git

    def slow(_argv, **kwargs):
        return original(["/bin/sh", "-c", "sleep 30"], **kwargs)

    monkeypatch.setattr(project_git_process, "run_network_git", slow)
    started = time.monotonic()
    result = cg.run(["push", ORIGIN, "main"])
    assert time.monotonic() - started < 3
    assert result.returncode == cg.TIMEOUT_EXIT_CODE
    assert "operation deadline" in result.stderr
    assert "yoke github connect" in result.stderr


def test_check_failure_retains_optional_credential_diagnosis(
    no_authorization, monkeypatch
):
    monkeypatch.setattr(
        cg,
        "_run_own_credentials",
        lambda argv, *_a: subprocess.CompletedProcess(argv, 128, "", "denied"),
    )
    with pytest.raises(subprocess.CalledProcessError, match="128") as error:
        cg.run(["push", ORIGIN, "main"], check=True)
    assert "your own git credentials did not work" in error.value.stderr


def test_connected_publication_labels_yoke_access_and_keeps_isolation(
    no_authorization, monkeypatch
):
    monkeypatch.setattr(cg, "resolve_token", lambda _url: "fixture-token")

    def push(argv, **kwargs):
        env = kwargs["env"]
        assert env["HOME"] != str(no_authorization)
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_ALLOW_PROTOCOL"] == "https"
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(cg, "_run", push)
    monkeypatch.setattr(
        cg, "_run_own_credentials", lambda *_a: pytest.fail("ambient auth must not run")
    )
    result = cg.run(["push", ORIGIN, "main"])
    assert result.credential_source == "pushed with Yoke GitHub access"
