"""Non-interactive HTTPS git transport helpers for onboarding.

The wizard owns the TTY, so every onboarding git op must run over HTTPS (no SSH
host-key prompt) and non-interactively (``GIT_TERMINAL_PROMPT=0`` fails fast
instead of prompting). These assert the URL shape, the auth-header encoding, the
non-interactive env, and that ``run_git`` injects the token only as a
URL-scoped header that never persists in ``.git/config`` and never leaks
into a raised error. Runs against a local temp repo — no network.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_git_transport as transport
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path, branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "--initial-branch", branch)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")


# ── URL + header shape ──────────────────────────────────────────────────


def test_https_remote_builds_clean_https_url_not_ssh() -> None:
    url = transport.https_remote("octocat/widget")
    assert url == "https://github.com/octocat/widget.git"
    assert not url.startswith("git@")
    assert "github.com" in url


def test_https_remote_uses_configured_ghes_web_origin() -> None:
    assert (
        transport.https_remote(
            "Octo/Widget",
            web_url="https://ghe.example:8443",
        )
        == "https://ghe.example:8443/Octo/Widget.git"
    )


def test_git_auth_header_encodes_x_access_token_as_basic() -> None:
    header = transport.git_auth_header("ghs_secret")
    assert header.startswith("AUTHORIZATION: basic ")
    encoded = header.split(" ", 2)[2]
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == "x-access-token:ghs_secret"


def test_git_auth_config_requires_exact_configured_github_origin() -> None:
    token = "ghu_short_lived"
    config = transport.git_auth_config(
        token,
        "https://ghe.example/Owner/Repo.git",
        web_url="https://ghe.example",
    )
    assert config is not None
    assert config.startswith("http.https://ghe.example/.extraheader=")
    assert (
        transport.git_auth_config(
            token,
            "https://attacker.example/Owner/Repo.git",
            web_url="https://ghe.example",
        )
        is None
    )


# ── non-interactive env ─────────────────────────────────────────────────


def test_non_interactive_env_disables_terminal_prompt() -> None:
    env = transport.non_interactive_git_env({})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # Residual SSH paths are hardened: batch mode + auto-trust unknown host keys
    # so no SSH op can ever stop on a prompt either.
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]


def test_non_interactive_env_replaces_inherited_ssh_command() -> None:
    env = transport.non_interactive_git_env({"GIT_SSH_COMMAND": "ssh -o Foo=bar"})
    assert env["GIT_SSH_COMMAND"] != "ssh -o Foo=bar"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_non_interactive_env_forces_trace_redaction() -> None:
    env = transport.non_interactive_git_env({"GIT_TRACE_REDACT": "0"})

    assert env["GIT_TRACE_REDACT"] == "1"


def test_non_interactive_env_forces_tls_verification_and_preserves_custom_ca() -> None:
    env = transport.non_interactive_git_env(
        {
            "GIT_SSL_NO_VERIFY": "1",
            "GIT_SSL_CAINFO": "/trusted/company-ca.pem",
        }
    )

    assert "GIT_SSL_NO_VERIFY" not in env
    assert env["GIT_SSL_CAINFO"] == "/trusted/company-ca.pem"


# ── run_git token injection + non-persistence ───────────────────────────


def test_run_git_runs_non_interactively(tmp_path: Path, monkeypatch) -> None:
    seen: dict = {}

    def _capture(cmd, **kwargs):
        seen["env"] = kwargs.get("env")
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "true\n", "")

    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setattr(transport, "run_network_git", _capture)

    token = "argv-secret"
    transport.run_git(repo, "rev-parse", "--is-inside-work-tree")

    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    # No token => no http.extraheader option on the argv.
    assert "http.extraheader" not in " ".join(seen["cmd"])
    assert token not in " ".join(seen["cmd"])
    auth_config = transport.git_auth_config(token, "https://github.com/octocat/app.git")
    assert auth_config is not None
    env = transport.git_config_env((auth_config,), base={})
    assert env["GIT_CONFIG_KEY_0"] == ("http.https://github.com/.extraheader")
    assert "AUTHORIZATION: basic" in env["GIT_CONFIG_VALUE_0"]


def test_run_git_rejects_token_for_non_github_remote(tmp_path: Path) -> None:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    # Stored origin is a local path, so no GitHub token is attached at all.
    transport.run_git(repo, "remote", "add", "origin", str(bare))

    token = "ghs_run_git_secret"
    with pytest.raises(ProjectOnboardError):
        transport.run_git(repo, "push", "-u", "origin", "main", token=token)

    assert "main" not in _git(bare, "branch", "--list")
    # SECURITY: the token never persists in config and never bakes into origin.
    config_text = (repo / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert "extraheader" not in config_text
    assert _git(repo, "remote", "get-url", "origin") == str(bare)


@pytest.mark.parametrize(
    ("remote", "web_url", "expected_key"),
    [
        (
            "https://github.com/octocat/widget.git",
            "https://github.com",
            "http.https://github.com/.extraheader",
        ),
        (
            "https://ghe.example/octocat/widget.git",
            "https://ghe.example",
            "http.https://ghe.example/.extraheader",
        ),
    ],
)
def test_run_git_scopes_auth_and_disables_redirects(
    tmp_path: Path,
    monkeypatch,
    remote: str,
    web_url: str,
    expected_key: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", remote)
    seen: dict = {}

    def capture(command, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 1, "", "push refused")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_short_lived",
            github_web_url=web_url,
        )
    env = seen["env"]
    assert expected_key in {
        env[key] for key in env if key.startswith("GIT_CONFIG_KEY_")
    }
    assert "http.followRedirects" in {
        env[key] for key in env if key.startswith("GIT_CONFIG_KEY_")
    }


def test_run_git_never_attaches_github_auth_to_unrelated_host(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", "https://attacker.example/o/r.git")
    seen: dict = {}
    push_launches: list[list[str]] = []

    def capture(command, **kwargs):
        push_launches.append(command)
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 1, "", "push refused")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_do_not_send",
            github_web_url="https://ghe.example",
        )
    assert push_launches == []
    assert seen == {}
