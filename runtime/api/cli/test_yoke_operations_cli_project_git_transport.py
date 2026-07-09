"""Non-interactive HTTPS git transport helpers for onboarding.

The wizard owns the TTY, so every onboarding git op must run over HTTPS (no SSH
host-key prompt) and non-interactively (``GIT_TERMINAL_PROMPT=0`` fails fast
instead of prompting). These assert the URL shape, the auth-header encoding, the
non-interactive env, and that ``run_git`` injects the token only as a
request-scoped header that never persists in ``.git/config`` and never leaks
into a raised error. Runs against a local temp repo — no network.
"""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_git_transport as transport
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.project_onboard_support import ProjectOnboardError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
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


def test_git_auth_header_encodes_x_access_token_as_basic() -> None:
    header = transport.git_auth_header("ghs_secret")
    assert header.startswith("AUTHORIZATION: basic ")
    encoded = header.split(" ", 2)[2]
    decoded = base64.b64decode(encoded).decode("utf-8")
    assert decoded == "x-access-token:ghs_secret"


# ── non-interactive env ─────────────────────────────────────────────────


def test_non_interactive_env_disables_terminal_prompt() -> None:
    env = transport.non_interactive_git_env({})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    # Residual SSH paths are hardened: batch mode + auto-trust unknown host keys
    # so no SSH op can ever stop on a prompt either.
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=accept-new" in env["GIT_SSH_COMMAND"]


def test_non_interactive_env_preserves_explicit_ssh_command() -> None:
    env = transport.non_interactive_git_env({"GIT_SSH_COMMAND": "ssh -o Foo=bar"})
    # A caller-supplied GIT_SSH_COMMAND is not clobbered.
    assert env["GIT_SSH_COMMAND"] == "ssh -o Foo=bar"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


# ── run_git token injection + non-persistence ───────────────────────────


def test_run_git_runs_non_interactively(tmp_path: Path, monkeypatch) -> None:
    seen: dict = {}
    real_run = subprocess.run

    def _capture(cmd, *args, **kwargs):
        seen["env"] = kwargs.get("env")
        seen["cmd"] = cmd
        return real_run(cmd, *args, **kwargs)

    repo = tmp_path / "repo"
    _init_repo(repo)
    monkeypatch.setattr(transport.subprocess, "run", _capture)

    transport.run_git(repo, "rev-parse", "--is-inside-work-tree")

    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    # No token => no http.extraheader option on the argv.
    assert "http.extraheader" not in " ".join(seen["cmd"])


def test_run_git_with_token_does_not_persist_or_leak(tmp_path: Path) -> None:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(bare))
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    # Stored origin is the clean URL; the token travels only in the -c header.
    transport.run_git(repo, "remote", "add", "origin", str(bare))

    token = "ghs_run_git_secret"
    transport.run_git(repo, "push", "-u", "origin", "main", token=token)

    # The push landed.
    assert "main" in _git(bare, "branch", "--list")
    # SECURITY: the token never persists in config and never bakes into origin.
    config_text = (repo / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config_text
    assert "extraheader" not in config_text
    assert _git(repo, "remote", "get-url", "origin") == str(bare)


# ── remote default-branch + reachability probes (ls-remote) ──────────────


def _seed_bare_with_branch(tmp_path: Path, name: str, branch: str) -> Path:
    """A bare repo whose HEAD points at ``branch`` — stands in for a GitHub source."""
    work = tmp_path / f"{name}-work"
    _init_repo(work, branch=branch)
    (work / "README.md").write_text("# x\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    bare = tmp_path / f"{name}.git"
    _git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


def test_remote_default_branch_reads_main(tmp_path: Path) -> None:
    bare = _seed_bare_with_branch(tmp_path, "source", "main")
    assert transport.remote_default_branch(str(bare)) == "main"


def test_remote_default_branch_reads_non_main_branch(tmp_path: Path) -> None:
    # A `master`-default source must report `master`, not a guessed `main` — this
    # is the exact mismatch the clone re-home guards against.
    bare = _seed_bare_with_branch(tmp_path, "source", "master")
    assert transport.remote_default_branch(str(bare)) == "master"


def test_remote_default_branch_returns_none_for_unreachable(tmp_path: Path) -> None:
    # A nonexistent local path fails fast (no network, no prompt) and the probe
    # degrades to None rather than crashing the wizard.
    assert transport.remote_default_branch(str(tmp_path / "nope.git")) is None


def test_remote_default_branch_none_for_empty_url() -> None:
    assert transport.remote_default_branch("") is None
    assert transport.remote_default_branch("   ") is None


def test_remote_default_branch_missing_git_raises_specific_error(monkeypatch) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)

    with pytest.raises(project_git_prerequisite.MissingGitError) as excinfo:
        transport.remote_default_branch("https://github.com/antirez/kilo.git")

    assert "git is required" in str(excinfo.value)


def test_remote_is_reachable_true_for_local_source(tmp_path: Path) -> None:
    bare = _seed_bare_with_branch(tmp_path, "source", "main")
    assert transport.remote_is_reachable(str(bare)) is True


def test_remote_is_reachable_false_for_unreachable(tmp_path: Path) -> None:
    assert transport.remote_is_reachable(str(tmp_path / "nope.git")) is False
    assert transport.remote_is_reachable("") is False


def test_remote_is_reachable_missing_git_raises_specific_error(monkeypatch) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)

    with pytest.raises(project_git_prerequisite.MissingGitError):
        transport.remote_is_reachable("https://github.com/antirez/kilo.git")


def test_run_git_failure_scrubs_token_header_from_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    token = "ghs_should_not_leak"
    # Push to a nonexistent remote so git fails; the -c header is on the argv and
    # could echo into stderr — the raised error must redact it.
    transport.run_git(
        repo, "remote", "add", "origin", str(tmp_path / "nope.git"),
    )
    with pytest.raises(ProjectOnboardError) as exc:
        transport.run_git(repo, "push", "origin", "main", token=token)

    message = str(exc.value)
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert token not in message
    assert encoded not in message
