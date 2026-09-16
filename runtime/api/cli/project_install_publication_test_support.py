"""Remote-backed checkout worlds for the install publication tests.

Publication is a git operation against a real remote, so the tests build a
real one: a bare repository, a seeding clone that stands in for a teammate's
machine, and the clone under test. Everything is local paths, so no test
touches the network.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from yoke_core.domain.project_install_test_helpers import make_bundle

OPERATOR_TEXT = "# Operator rules\n\nkeep this paragraph\n"
MANAGED_BLOCK = "yoke managed content, current version\n"
STALE_BLOCK = "yoke managed content, older version\n"

PROTECTED_PRE_RECEIVE_HOOK = """#!/bin/sh
while read old new ref; do
  if [ "$ref" = "refs/heads/main" ]; then
    echo "remote: error: GH006: Protected branch update failed." >&2
    echo "remote: error: Changes must be made through a pull request." >&2
    exit 1
  fi
done
exit 0
"""

REJECTING_PRE_RECEIVE_HOOK = """#!/bin/sh
echo "remote: Permission to demo/demo.git denied." >&2
echo "remote: error: HTTP 403" >&2
exit 1
"""


@dataclass(frozen=True)
class RemoteWorld:
    """A bare remote, a teammate's clone, and the checkout under test."""

    remote: Path
    teammate: Path
    checkout: Path

    def advance_remote(self, *, path: str, content: str, message: str) -> str:
        """Land a commit on the remote from the teammate's clone."""
        target = self.teammate / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        git(self.teammate, "add", "-A")
        git(self.teammate, "commit", "-q", "-m", message)
        git(self.teammate, "push", "-q", "origin", "main")
        return git(self.remote, "rev-parse", "main").stdout.strip()

    def remote_subjects(self) -> list[str]:
        listed = git(self.remote, "log", "--format=%s", "main").stdout
        return [line for line in listed.splitlines() if line.strip()]

    def remote_tip(self) -> str:
        return git(self.remote, "rev-parse", "main").stdout.strip()

    def remote_branches(self) -> list[str]:
        listed = git(self.remote, "for-each-ref", "--format=%(refname:short)")
        return [line.strip() for line in listed.stdout.splitlines() if line.strip()]

    def is_clean(self) -> bool:
        return not git(self.checkout, "status", "--porcelain").stdout.strip()


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def identify(root: Path) -> None:
    git(root, "config", "user.email", "publication@test.invalid")
    git(root, "config", "user.name", "Publication Test")


def remote_world(
    tmp_path: Path, *, pre_receive_hook: str | None = None,
) -> RemoteWorld:
    """Build the bare remote, seed it, and clone the checkout under test."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True,
    )
    teammate = tmp_path / "teammate"
    teammate.mkdir()
    git(teammate, "init", "-q", "-b", "main")
    identify(teammate)
    (teammate / "README.md").write_text("project\n", encoding="utf-8")
    (teammate / "AGENTS.md").write_text(OPERATOR_TEXT, encoding="utf-8")
    git(teammate, "add", "-A")
    git(teammate, "commit", "-q", "-m", "seed")
    git(teammate, "remote", "add", "origin", str(remote))
    git(teammate, "push", "-q", "-u", "origin", "main")
    if pre_receive_hook is not None:
        hook = remote / "hooks" / "pre-receive"
        hook.write_text(pre_receive_hook, encoding="utf-8")
        hook.chmod(0o755)
    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(checkout)], check=True,
    )
    identify(checkout)
    return RemoteWorld(remote=remote, teammate=teammate, checkout=checkout)


def local_only_checkout(tmp_path: Path) -> Path:
    """A git checkout with no remote at all — an intentional outcome."""
    root = tmp_path / "local-only"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    identify(root)
    (root / "README.md").write_text("project\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "seed")
    return root


def agents_markdown(block: str) -> str:
    """``AGENTS.md`` as an install leaves it: a managed block, then their text.

    The block is rendered through the product's own marker renderer, so a
    test never hand-writes markers that could drift from the real ones.
    """
    from yoke_contracts.project_contract.managed_block import render_block

    return f"{render_block(block)}\n\n{OPERATOR_TEXT}"


def managed_bundle(block: str = MANAGED_BLOCK) -> dict:
    """A bundle that also renders one managed block into ``AGENTS.md``."""
    bundle = make_bundle()
    bundle["managed_markdown"] = {
        "blocks": {"rules": block},
        "targets": [{"path": "AGENTS.md", "block": "rules"}],
    }
    return bundle


def bind_bundle(monkeypatch, bundle: dict | None = None) -> None:
    """Point the install runner at a fake bundle and skip machine registration."""
    from yoke_cli.project_install import runner

    monkeypatch.setattr(
        runner, "_resolve_bundle",
        lambda *_a, **_k: (bundle if bundle is not None else managed_bundle(), "test"),
    )
    monkeypatch.setattr(
        runner, "_register_in_machine_config", lambda *_a, **_k: False,
    )


__all__ = [
    "MANAGED_BLOCK",
    "OPERATOR_TEXT",
    "PROTECTED_PRE_RECEIVE_HOOK",
    "REJECTING_PRE_RECEIVE_HOOK",
    "RemoteWorld",
    "STALE_BLOCK",
    "agents_markdown",
    "bind_bundle",
    "git",
    "identify",
    "local_only_checkout",
    "managed_bundle",
    "remote_world",
]
