"""Reading a file as one commit's parent held it, and the ways that fails.

The proof that a commit stayed inside its managed block compares the
operator's text before and after, so everything rests on the "before". Two
readings look identical and mean opposite things: nothing existed to change
clears the commit, while a comparison that could not be performed must refuse
it. These cover both, at both places the distinction is decided — the
commit's own parent header, and the parent tree's copy of the file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_cli.project_install import publication_commit_ownership as ownership
from yoke_cli.project_install import publication_commit_parent as parent_read
from yoke_cli.project_install import runner

from runtime.api.cli.project_install_publication_test_support import (
    MANAGED_BLOCK,
    STALE_BLOCK,
    agents_markdown,
    bind_bundle,
    git,
    identify,
    managed_bundle,
    managed_markdown_only,
    remote_world,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def _fail_git_verb(
    monkeypatch: pytest.MonkeyPatch, verb: str, detail: str,
) -> None:
    """Make one git verb fail while every other call runs for real."""
    real_run_git = ownership.checkout_gate.run_git

    def selective(
        repo_root: Path, *args: str,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == verb:
            return subprocess.CompletedProcess(["git", verb], 128, "", detail)
        return real_run_git(repo_root, *args)

    monkeypatch.setattr(ownership.checkout_gate, "run_git", selective)


def test_a_commit_that_created_the_co_owned_file_is_still_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing existed before, so nothing outside the block was changed.

    The proof compares the operator's text before and after. Where the
    commit created the file that comparison has no "before", and reading
    the missing parent as an operator edit would refuse the install its own
    first write of a co-owned file.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    git(world.checkout, "rm", "-q", "AGENTS.md")
    git(world.checkout, "commit", "-q", "-m", "operator drops the file")
    parent = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    (world.checkout / "AGENTS.md").write_text(
        managed_markdown_only(MANAGED_BLOCK), encoding="utf-8",
    )
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.9")
    recreated = git(world.checkout, "rev-parse", "HEAD").stdout.strip()

    unproven = ownership.unproven_commits(
        ownership.read_local_only_commits(world.checkout, parent, recreated)[0],
        territory,
        repo_root=world.checkout,
    )

    assert unproven == ()


def test_an_unreadable_parent_refuses_rather_than_claiming_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed parent read is not evidence the file did not exist.

    Genuine absence and an unreadable parent arrive as the same failure, and
    they are opposite answers: absence clears the commit, while an unreadable
    parent means the comparison never happened. Treating both as absence
    would let any git failure authorize a destructive reconcile.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    (world.checkout / "AGENTS.md").write_text(
        agents_markdown(STALE_BLOCK), encoding="utf-8",
    )
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.8")
    parent = git(world.checkout, "rev-parse", "HEAD~1").stdout.strip()
    local = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    commits = ownership.read_local_only_commits(world.checkout, parent, local)[0]
    _fail_git_verb(monkeypatch, "ls-tree", "fatal: bad object")

    unproven = ownership.unproven_commits(
        commits, territory, repo_root=world.checkout,
    )

    assert len(unproven) == 1
    assert "outside the managed block" in unproven[0]


def test_a_root_commit_records_no_parent_so_nothing_preceded_it(
    tmp_path: Path,
) -> None:
    """Only the commit's own header proves it is a root commit.

    Resolving ``<sha>^`` fails for a root commit and for a parent that is
    merely unavailable, so the header is what separates them. A real root
    commit genuinely had nothing before it, and the proof must clear it.
    """
    root = tmp_path / "fresh"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    identify(root)
    (root / "AGENTS.md").write_text(
        managed_markdown_only(MANAGED_BLOCK), encoding="utf-8",
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Install Yoke operating layer 9.9.9")
    first = git(root, "rev-parse", "HEAD").stdout.strip()

    parents, header_read = parent_read.recorded_parents(root, first)
    before, state = parent_read.parent_text(root, first, "AGENTS.md")
    unproven = ownership.unproven_commits(
        (
            ownership.LocalCommit(
                sha=first,
                subject="Install Yoke operating layer 9.9.9",
                changed_paths=("AGENTS.md",),
            ),
        ),
        ownership.InstallerTerritory(managed_regions=frozenset({"AGENTS.md"})),
        repo_root=root,
    )

    assert header_read is True
    assert parents == ()
    assert (before, state) == ("", parent_read.ABSENT)
    assert unproven == ()


def test_an_unresolvable_parent_on_a_non_root_commit_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent that cannot be resolved proves nothing about what preceded.

    This is the failure a root commit is indistinguishable from once the
    question is asked as ``<sha>^``: both come back empty. Reading the
    commit's own header instead means a non-root commit whose parent cannot
    be read refuses, rather than being cleared as a creation.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    rewrite = world.checkout / "AGENTS.md"
    rewrite.write_text(agents_markdown(STALE_BLOCK), encoding="utf-8")
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.8")
    parent = git(world.checkout, "rev-parse", "HEAD~1").stdout.strip()
    local = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    commits = ownership.read_local_only_commits(world.checkout, parent, local)[0]
    _fail_git_verb(monkeypatch, "cat-file", "fatal: unable to read object")

    parents, header_read = parent_read.recorded_parents(world.checkout, local)
    before, state = parent_read.parent_text(world.checkout, local, "AGENTS.md")
    unproven = ownership.unproven_commits(
        commits, territory, repo_root=world.checkout,
    )

    assert header_read is False
    assert parents == ()
    assert (before, state) == ("", parent_read.UNREADABLE)
    assert len(unproven) == 1
    assert "outside the managed block" in unproven[0]
