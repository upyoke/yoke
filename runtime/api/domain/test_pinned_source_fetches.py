"""Pinned deploy and QA source fetches use stored, prompt-free authorization."""

from __future__ import annotations

import base64
import subprocess

import pytest

from yoke_cli.config import credentialed_git as cg
from yoke_cli.config import credentialed_git_command as commands
from yoke_cli.config import repo_upstream_git
from yoke_core.domain import deploy_pipeline_pinned_source as pinned
from yoke_core.domain import qa_candidate_checkout as candidate
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

ORIGIN = "https://github.com/example/project.git"


@pytest.fixture(params=["deploy", "qa"])
def fetch_source(request, monkeypatch, tmp_path):
    module, resolver, error = (
        (pinned, "_resolve_commit", pinned.DeployPinnedSourceError)
        if request.param == "deploy"
        else (candidate, "_commit", QaCaseExecutionError)
    )

    def bare_run(args, **kwargs):
        assert not commands.is_network_command(args), "bare network git call"
        raise AssertionError("unexpected local operation")

    monkeypatch.setattr(module, "_run", bare_run)
    monkeypatch.setattr(cg, "configured_web_url", lambda: "https://github.com")
    monkeypatch.setattr(commands, "remote_url", lambda *_: ORIGIN)
    monkeypatch.setattr(repo_upstream_git, "network_timeout_seconds", lambda: 17)

    def run(sha=""):
        commits = iter(["", sha])
        monkeypatch.setattr(module, resolver, lambda *_: next(commits))
        if module is pinned:
            return pinned._ensure_commit(str(tmp_path), "revision")
        return candidate._candidate_commit(tmp_path, "revision", "deployment run")

    return run, error, tmp_path


def test_fetch_uses_only_stored_authorization(fetch_source, monkeypatch):
    fetch, _, repo = fetch_source
    token = "stored-test-token"
    monkeypatch.setattr(cg, "resolve_token", lambda _: token)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "ambient-helper")
    calls = []

    def execute(argv, **kwargs):
        env = kwargs["env"]
        assert argv == [
            "git",
            "-C",
            str(repo),
            "fetch",
            "--quiet",
            "origin",
            "revision",
        ]
        assert kwargs["timeout"] == 17
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        entries = [
            (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        ]
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        assert (
            f"http.{ORIGIN}.extraheader",
            f"AUTHORIZATION: basic {encoded}",
        ) in entries
        assert ("credential.helper", "") in entries
        assert ("credential.helper", "ambient-helper") not in entries
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(cg.subprocess, "run", execute)
    assert fetch("f" * 40) == "f" * 40
    assert len(calls) == 1


def test_unavailable_stored_authorization_refuses_before_subprocess(
    fetch_source, monkeypatch
):
    fetch, error, _ = fetch_source
    monkeypatch.setattr(
        "yoke_cli.config.machine_config.github_config",
        lambda _path: {"authorization": {"status": "authorized"}},
    )

    def missing(_):
        raise cg.CredentialedGitError(
            f"stored authorization missing. {cg.RECONNECT_RECOVERY}"
        )

    def unexpected(*args, **kwargs):
        raise AssertionError("no subprocess or credential prompt may start")

    monkeypatch.setattr(cg, "resolve_token", missing)
    monkeypatch.setattr(cg.subprocess, "run", unexpected)
    with pytest.raises(error, match="stored authorization missing") as refusal:
        fetch()
    assert "yoke github connect" in str(refusal.value)


def test_timeout_preserves_named_runner_recovery(fetch_source, monkeypatch):
    fetch, error, _ = fetch_source
    monkeypatch.setattr(cg, "resolve_token", lambda _: "stored-test-token")

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(cg.subprocess, "run", timeout)
    with pytest.raises(error, match="did not finish within 17s") as refusal:
        fetch()
    assert "non-interactively" in str(refusal.value)
    assert cg.TRANSIENT_RECOVERY in str(refusal.value)
