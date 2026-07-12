"""Remote probes and diagnostic scrubbing for onboarding Git transport."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

import pytest

from yoke_cli.config import project_git_prerequisite
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


def test_remote_default_branch_reads_main(monkeypatch) -> None:
    monkeypatch.setattr(
        transport,
        "run_network_git",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            "ref: refs/heads/main\tHEAD\n",
            "",
        ),
    )
    assert transport.remote_default_branch("git@github.com:acme/source.git") == "main"


def test_remote_default_branch_reads_non_main_branch(monkeypatch) -> None:
    # A `master`-default source must report `master`, not a guessed `main` — this
    # is the exact mismatch the clone re-home guards against.
    monkeypatch.setattr(
        transport,
        "run_network_git",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            "ref: refs/heads/master\tHEAD\n",
            "",
        ),
    )
    assert (
        transport.remote_default_branch("https://github.com/acme/source.git")
        == "master"
    )


@pytest.mark.parametrize("hostile", ["--help", "feature/.hidden", "main\x1b]2;x"])
def test_remote_default_branch_rejects_hostile_symref(monkeypatch, hostile) -> None:
    monkeypatch.setattr(
        transport,
        "run_network_git",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, f"ref: refs/heads/{hostile}\tHEAD\n", "",
        ),
    )

    assert transport.remote_default_branch(
        "https://github.com/acme/source.git",
    ) is None


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


def test_remote_is_reachable_true_for_github_source(monkeypatch) -> None:
    monkeypatch.setattr(
        transport,
        "run_network_git",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            "",
            "",
        ),
    )
    assert transport.remote_is_reachable("https://github.com/acme/source.git") is True


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
        repo,
        "remote",
        "add",
        "origin",
        str(tmp_path / "nope.git"),
    )
    with pytest.raises(ProjectOnboardError) as exc:
        transport.run_git(repo, "push", "origin", "main", token=token)

    message = str(exc.value)
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    assert token not in message
    assert encoded not in message


def test_git_diagnostic_neutralizes_hostile_terminal_sequences() -> None:
    token = "ghs_should_not_leak"
    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    rendered = transport.scrub_git_diagnostic(
        f"denied {token} {encoded}\x1b]2;spoofed title\x07\x9b31m",
        token=token,
    )

    assert token not in rendered
    assert encoded not in rendered
    assert "spoofed title" in rendered
    assert all(ord(char) >= 32 and ord(char) != 127 for char in rendered)
