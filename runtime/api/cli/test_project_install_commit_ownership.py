"""Proving a local commit is the installer's, not the operator's.

Publication may replace the commits a branch carries, so it must first
establish that they are its own. These cover what that proof must refuse: a
commit wearing the installer's title over someone else's changes, a commit
list that could not be read, and — for a file the install only co-owns — a
change to the operator's text around its managed block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.project_install import publication_commit_ownership as ownership
from yoke_cli.project_install import publication_reconcile as reconcile
from yoke_cli.project_install import runner

from runtime.api.cli.project_install_publication_test_support import (
    STALE_BLOCK,
    agents_markdown,
    bind_bundle,
    git,
    managed_bundle,
    remote_world,
    rewrite_outside_block,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def test_reconcile_refuses_when_the_operator_owns_a_local_commit(
    tmp_path: Path,
) -> None:
    world = remote_world(tmp_path)
    (world.checkout / "operator.md").write_text("mine\n", encoding="utf-8")
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "operator work")
    world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )
    local = git(world.checkout, "rev-parse", "main").stdout.strip()

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
        territory=ownership.installer_territory(world.checkout),
    )

    assert outcome["status"] == "unproven_commits_present"
    assert any("operator work" in line for line in outcome["unproven_commits"])
    assert "git pull --rebase origin main" in outcome["recovery"]
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == local


def test_an_installer_subject_over_unowned_changes_is_not_treated_as_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching subject is not proof; the diff has to stay in our territory.

    Anyone can type the installer's commit message. Replacing a commit on
    that basis alone would discard, or publish, work that is not ours.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    (world.checkout / "operator_notes.md").write_text("mine\n", encoding="utf-8")
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.9")
    disguised = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
        territory=territory,
    )

    assert outcome["status"] == "unproven_commits_present"
    assert any(
        "operator_notes.md" in line for line in outcome["unproven_commits"]
    )
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == disguised
    assert (world.checkout / "operator_notes.md").is_file()


def test_an_unreadable_commit_list_refuses_instead_of_reading_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No commits and unreadable commits are different answers."""
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    runner.install(world.checkout, project_id=7, publish=False)
    world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )
    monkeypatch.setattr(
        ownership,
        "read_local_only_commits",
        lambda *_a, **_k: ((), False, "could not read the commits: git log exploded"),
    )
    before = git(world.checkout, "rev-parse", "main").stdout.strip()

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
        territory=ownership.InstallerTerritory(),
    )

    assert outcome["status"] == "local_commits_unreadable"
    assert outcome["commits_read"] is False
    assert "git log exploded" in outcome["recovery"]
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == before


def test_a_change_outside_the_managed_block_is_the_operators_not_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install owns its marked block, not the whole co-owned file.

    A commit titled like an install that leaves the block untouched and
    edits only the operator's surrounding prose is theirs. Owning the path
    would let publication reset or publish that text.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    assert "AGENTS.md" in territory.managed_regions
    assert "AGENTS.md" not in territory.whole_files
    rewrite_outside_block(world.checkout / "AGENTS.md", "my own paragraph\n")
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.9")
    theirs = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
        territory=territory,
    )

    assert outcome["status"] == "unproven_commits_present"
    assert any(
        "outside the managed block" in line and "AGENTS.md" in line
        for line in outcome["unproven_commits"]
    )
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == theirs
    assert "my own paragraph" in (
        world.checkout / "AGENTS.md"
    ).read_text(encoding="utf-8")


def test_a_change_confined_to_the_managed_block_stays_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The proof must not refuse the install's own block rewrite."""
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    runner.install(world.checkout, project_id=7, publish=False)
    territory = ownership.installer_territory(world.checkout)
    (world.checkout / "AGENTS.md").write_text(
        agents_markdown(STALE_BLOCK), encoding="utf-8",
    )
    git(world.checkout, "add", "-A")
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.8")

    unproven = ownership.unproven_commits(
        ownership.read_local_only_commits(
            world.checkout,
            git(world.checkout, "rev-parse", "HEAD~1").stdout.strip(),
            git(world.checkout, "rev-parse", "HEAD").stdout.strip(),
        )[0],
        territory,
        repo_root=world.checkout,
    )

    assert unproven == ()


