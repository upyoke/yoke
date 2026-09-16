"""Generating against current upstream, and reconciling a remote that moved.

The defect these cover is one an operator hit: a checkout whose default
branch was behind the remote generated its layer on the stale base, and the
merge that followed kept the older side's non-conflicting generated content,
leaving obsolete teaching in the tree. Reconciliation here is regeneration on
the updated revision, so the published content is exactly what this Yoke
version renders.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.project_install import publication_outcome
from yoke_cli.project_install import publication_reconcile as reconcile
from yoke_cli.project_install import repository_layer
from yoke_cli.project_install import runner
from yoke_cli.project_install.files import ProjectInstallError

from runtime.api.cli.project_install_publication_test_support import (
    MANAGED_BLOCK,
    OPERATOR_TEXT,
    STALE_BLOCK,
    agents_markdown,
    bind_bundle,
    git,
    local_only_checkout,
    managed_bundle,
    remote_world,
)


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def test_install_records_the_shared_freshness_reading_it_generated_against(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    advanced = world.advance_remote(
        path="teammate.md", content="landed first\n", message="teammate change",
    )
    bind_bundle(monkeypatch)

    report = runner.install(world.checkout, project_id=7)

    upstream = report["checkout"]["upstream"]
    assert upstream["state"] == "fast_forwarded"
    assert upstream["verified"] is True
    assert upstream["local_branch_current"] is True
    assert upstream["upstream_sha"] == advanced
    assert (world.checkout / "teammate.md").is_file()


def test_an_unreadable_remote_degrades_the_install_rather_than_refusing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install materializes a local layer, so an offline machine still gets it.

    Preparation refuses an unverifiable remote because a lane would have no
    revision to start from. This consumer degrades instead and lets
    publication carry the refusal, so the operator is never told the remote
    holds a layer it never received.
    """
    world = remote_world(tmp_path)
    git(world.checkout, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    bind_bundle(monkeypatch)

    report = runner.install(world.checkout, project_id=7)

    upstream = report["checkout"]["upstream"]
    assert upstream["verified"] is False
    assert upstream["state"] == "fetch_failed"
    assert any(
        warning.startswith("upstream freshness:")
        for warning in report.get("warnings", [])
    )
    assert report["commit"]["status"] == "created"
    assert report["publication"]["status"] == publication_outcome.PENDING


def test_publication_refuses_to_guess_among_several_untracked_remotes(
    tmp_path: Path,
) -> None:
    world = remote_world(tmp_path)
    git(world.checkout, "remote", "add", "mirror", str(world.remote))
    git(world.checkout, "config", "--unset", "branch.main.remote")

    state = reconcile.read_remote_state(world.checkout, branch="main")

    assert state.status == reconcile.REMOTE_UNRESOLVED
    assert "set-upstream-to" in state.detail


def test_a_checkout_with_no_remote_reports_no_remote(tmp_path: Path) -> None:
    root = local_only_checkout(tmp_path)

    state = reconcile.read_remote_state(root, branch="main")

    assert state.status == reconcile.NO_REMOTE


def test_reconcile_regenerates_current_content_over_the_older_sides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch, managed_bundle())
    installer_commit = _commit_stale_layer(world.checkout)
    world.advance_remote(
        path="AGENTS.md",
        content=agents_markdown(STALE_BLOCK),
        message="teammate change",
    )
    regenerated: list[int] = []

    def regenerate() -> dict:
        regenerated.append(1)
        return repository_layer.write_repository_layer(
            world.checkout,
            managed_bundle(),
            operation="install",
            source="test",
            mode="copy",
        )

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=regenerate,
        operation="install",
    )

    assert outcome["status"] == "regenerated"
    assert regenerated == [1]
    published = (world.checkout / "AGENTS.md").read_text(encoding="utf-8")
    assert MANAGED_BLOCK.strip() in published
    assert STALE_BLOCK.strip() not in published
    assert OPERATOR_TEXT.strip() in published
    assert installer_commit not in git(
        world.checkout, "log", "--format=%H", "main",
    ).stdout
    assert world.is_clean()


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
    )

    assert outcome["status"] == "operator_commits_present"
    assert any("operator work" in line for line in outcome["operator_commits"])
    assert "git pull --rebase origin main" in outcome["recovery"]
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == local


def test_reconcile_reports_already_published_when_the_remote_has_it(
    tmp_path: Path,
) -> None:
    world = remote_world(tmp_path)

    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
    )

    assert outcome["status"] == "already_published"


def test_moving_the_branch_refuses_a_dirty_tree_instead_of_discarding_it(
    tmp_path: Path,
) -> None:
    world = remote_world(tmp_path)
    advanced = world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )
    (world.checkout / "uncommitted.md").write_text("mine\n", encoding="utf-8")

    with pytest.raises(ProjectInstallError) as raised:
        reconcile.move_branch_onto(world.checkout, branch="main", sha=advanced)

    message = str(raised.value)
    assert "uncommitted.md" in message
    assert "git add -A && git commit" in message
    assert (world.checkout / "uncommitted.md").read_text(
        encoding="utf-8",
    ) == "mine\n"


def test_a_behind_clone_publishes_a_child_of_the_current_remote_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = remote_world(tmp_path)
    advanced = world.advance_remote(
        path="teammate.md", content="landed first\n", message="teammate change",
    )
    bind_bundle(monkeypatch)

    report = runner.install(world.checkout, project_id=7)

    assert report["checkout"]["upstream"]["state"] == "fast_forwarded"
    assert report["publication"]["status"] == publication_outcome.PUBLISHED
    parents = git(
        world.checkout, "rev-parse", f"{report['commit']['sha']}^",
    ).stdout.strip()
    assert parents == advanced
    assert world.remote_subjects()[0].startswith("Install Yoke operating layer")
    assert (world.checkout / "teammate.md").is_file()


def _commit_stale_layer(checkout: Path) -> str:
    """Stand in for an installer commit built on the pre-advance revision."""
    target = checkout / "AGENTS.md"
    target.write_text(agents_markdown(STALE_BLOCK), encoding="utf-8")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.8")
    return git(checkout, "rev-parse", "HEAD").stdout.strip()
