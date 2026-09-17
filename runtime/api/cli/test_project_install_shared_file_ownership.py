"""The install may not claim a whole file it only merges its entries into.

Hook settings and the ignore files carry the install's content inside the
operator's own document: a merged JSON hook subtree, an appended ignore line.
Nothing there separates the two authors, so the install cannot show a commit
touching one stayed on its side — and a commit it cannot show is its own is
neither reset nor published. These cover that refusal on both paths, plus the
one commit that needs no inference: the one this run just made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.project_install import publication_commit_ownership as ownership
from yoke_cli.project_install import publication_eligibility as eligibility
from yoke_cli.project_install import publication_outcome as outcome_layer
from yoke_cli.project_install import publication_reconcile as reconcile
from yoke_cli.project_install import runner

from runtime.api.cli.project_install_publication_test_support import (
    bind_bundle,
    git,
    remote_world,
)

CLAUDE_SETTINGS_REL = ".claude/settings.json"
GITIGNORE_REL = ".gitignore"


@pytest.fixture(autouse=True)
def _isolated_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


def _edit_hook_settings(root: Path) -> None:
    """Add an operator-authored key beside the install's hook entries."""
    target = root / CLAUDE_SETTINGS_REL
    document = json.loads(target.read_text(encoding="utf-8"))
    document["operatorOwnedSetting"] = "mine"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _edit_gitignore(root: Path) -> None:
    """Append an operator-authored ignore line to the shared ignore file."""
    target = root / GITIGNORE_REL
    target.write_text(
        target.read_text(encoding="utf-8") + "my-scratch-dir/\n", encoding="utf-8",
    )


@pytest.mark.parametrize(
    "shared_path, operator_edit",
    [
        (CLAUDE_SETTINGS_REL, _edit_hook_settings),
        (GITIGNORE_REL, _edit_gitignore),
    ],
)
def test_an_installer_subject_editing_a_shared_file_is_neither_reset_nor_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shared_path: str,
    operator_edit,
) -> None:
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    report = runner.install(world.checkout, project_id=7, publish=False)
    ours = str(report["commit"]["sha"])
    territory = ownership.installer_territory(
        world.checkout, own_commits=(ours,),
    )
    assert shared_path in territory.shared_files
    assert shared_path not in territory.whole_files
    operator_edit(world.checkout)
    git(world.checkout, "add", "-A", "--", shared_path)
    git(world.checkout, "commit", "-q", "-m", "Install Yoke operating layer 9.9.9")
    theirs = git(world.checkout, "rev-parse", "HEAD").stdout.strip()
    edited = (world.checkout / shared_path).read_text(encoding="utf-8")
    world.advance_remote(
        path="teammate.md", content="theirs\n", message="teammate change",
    )

    publish = eligibility.push_eligibility(
        world.checkout, branch="main", remote="origin", territory=territory,
    )
    outcome = reconcile.reconcile_by_regeneration(
        world.checkout,
        branch="main",
        remote="origin",
        regenerate=lambda: pytest.fail("regeneration must not run"),
        operation="install",
        territory=territory,
    )

    assert publish["status"] == outcome_layer.PENDING
    assert shared_path in publish["detail"]
    assert outcome["status"] == "unproven_commits_present"
    assert outcome["unproven_commits"] == [
        line
        for line in outcome["unproven_commits"]
        if shared_path in line and "shares with the operator" in line
    ]
    assert len(outcome["unproven_commits"]) == 1
    assert git(world.checkout, "rev-parse", "main").stdout.strip() == theirs
    assert world.remote_tip() != theirs
    assert (world.checkout / shared_path).read_text(encoding="utf-8") == edited


def test_this_runs_own_commit_publishes_the_shared_files_it_merged_into(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity, not inference, is what carries an ordinary install.

    The install legitimately merges its entries into the shared files, so a
    proof that refused every commit touching one would refuse every install.
    The commit publication is about to push is the one it just made, and it
    knows it by sha.
    """
    world = remote_world(tmp_path)
    bind_bundle(monkeypatch)
    report = runner.install(world.checkout, project_id=7)

    publication = report["publication"]

    assert publication["status"] == outcome_layer.PUBLISHED
    assert world.remote_tip() == str(report["commit"]["sha"])
    assert CLAUDE_SETTINGS_REL in report["commit"]["paths"]
