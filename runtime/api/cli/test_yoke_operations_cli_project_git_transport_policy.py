"""Repository-policy guards and remote probes for onboarding Git transport."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("remote", "policy_key"),
    [
        (
            "https://github.com/acme/widgets.git",
            "http.https://github.com/acme/widgets.git.sslCAInfo",
        ),
        (
            "ssh://git@github.com/acme/widgets.git",
            "http.https://github.com/acme/widgets.git.sslCAInfo",
        ),
        (
            "git@github.com:acme/widgets.git",
            "http.https://github.com/acme/widgets.git.curloptResolve",
        ),
    ],
)
def test_authenticated_push_rejects_policy_for_canonical_https_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote: str,
    policy_key: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", remote)
    _git(repo, "config", "--local", policy_key, "/tmp/hostile-policy")
    launches: list[list[str]] = []

    def capture(command, **_kwargs):
        launches.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(
        ProjectOnboardError,
        match="repository-local Git HTTP overrides",
    ):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_do_not_route",
        )

    assert launches == []


def test_authenticated_push_ignores_unrelated_local_http_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "git@github.com:acme/widgets.git",
    )
    _git(
        repo,
        "config",
        "--local",
        "http.https://attacker.example/.sslCAInfo",
        "/tmp/unrelated-ca",
    )
    launches: list[list[str]] = []

    def capture(command, **_kwargs):
        launches.append(command)
        return subprocess.CompletedProcess(command, 1, "", "push refused")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError, match="push refused"):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_scoped",
        )

    assert launches == [
        [
            "git",
            "push",
            "https://github.com/acme/widgets.git",
            "main",
        ]
    ]


def test_authenticated_push_rejects_rewrite_of_canonicalized_ssh_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "ssh://git@github.com/acme/widgets.git",
    )
    _git(
        repo,
        "config",
        "--local",
        "url.https://attacker.invalid/evil/.insteadOf",
        "https://github.com/",
    )
    launches: list[list[str]] = []

    def capture(command, **_kwargs):
        launches.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError, match="Git URL rewriting"):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_do_not_redirect",
        )

    assert launches == []


def test_authenticated_push_disables_signing_and_recursive_submodule_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/acme/widgets.git",
    )
    _git(repo, "config", "--local", "push.gpgSign", "true")
    _git(repo, "config", "--local", "push.recurseSubmodules", "on-demand")
    observed: dict[str, str] = {}

    def capture(command, **kwargs):
        env = kwargs["env"]
        count = int(env["GIT_CONFIG_COUNT"])
        observed.update(
            {
                env[f"GIT_CONFIG_KEY_{index}"]: env[f"GIT_CONFIG_VALUE_{index}"]
                for index in range(count)
            }
        )
        return subprocess.CompletedProcess(command, 1, "", "push refused")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError, match="push refused"):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_parent_only",
        )

    assert observed["push.gpgSign"] == "false"
    assert observed["push.recurseSubmodules"] == "no"


@pytest.mark.parametrize(
    "program_key",
    [
        "gpg.program",
        "gpg.ssh.program",
    ],
)
def test_authenticated_push_rejects_repo_signing_program_before_token_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    program_key: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/acme/widgets.git",
    )
    marker = tmp_path / "token-environment-exfiltrated"
    program = tmp_path / "signing-program.py"
    program.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('invoked', encoding='utf-8')\n",
        encoding="utf-8",
    )
    program.chmod(0o700)
    _git(repo, "config", "--local", "push.gpgSign", "true")
    _git(repo, "config", "--local", program_key, str(program))
    launches: list[list[str]] = []

    def capture(command, **_kwargs):
        launches.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(transport, "run_network_git", capture)
    with pytest.raises(ProjectOnboardError, match="Git signing programs"):
        transport.run_git(
            repo,
            "push",
            "origin",
            "main",
            token="ghu_never_exposed",
        )

    assert launches == []
    assert not marker.exists()
