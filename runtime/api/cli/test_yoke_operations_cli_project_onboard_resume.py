"""Resumable / idempotent apply for the clone-onboarding path.

A re-run after a partial onboarding must pick up where it stopped, not hard-fail
on a half-written checkout. These drive the apply-layer steps against local temp
git repos (a bare repo stands in for the GitHub source/remote): the clone step
skips an already-present clone and errors with a recovery message on a genuine
conflict; the re-home and fork remote steps are idempotent on a second run.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    seed_remote,
    write_https_config,
)
from runtime.api.cli.project_onboard_github_replay_test_support import (
    CreateRepoReplay,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import github_publish
from yoke_cli.config import github_publish_transport
from yoke_cli.config import project_clone_resume
from yoke_cli.config import project_clone_support as clone
from yoke_cli.config import project_onboard
from yoke_cli.config.project_onboard import ProjectOnboardError


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return result.stdout.strip()


def _seed_bare_source(tmp_path: Path, name: str = "source") -> Path:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    _git(work, "init", "--initial-branch", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("# source\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "seed")
    bare = tmp_path / f"{name}.git"
    _git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


def _clone_into(tmp_path: Path, bare: Path, name: str) -> Path:
    parent = tmp_path / "checkouts"
    parent.mkdir(exist_ok=True)
    _git(parent, "clone", str(bare), name)
    target = parent / name
    _git(target, "config", "user.email", "t@example.com")
    _git(target, "config", "user.name", "Test")
    return target


# ── existing_clone_matches / origin_is ───────────────────────────────────


def test_existing_clone_matches_a_present_clone(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    target = _clone_into(tmp_path, source, "widgets")
    assert clone.existing_clone_matches(target, str(source)) is True


def test_existing_clone_matches_false_for_empty_or_foreign(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    other = _seed_bare_source(tmp_path, "other")
    target = _clone_into(tmp_path, other, "widgets")
    # Empty dir is not a clone; a clone of a different repo doesn't match.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert clone.existing_clone_matches(empty, str(source)) is False
    assert clone.existing_clone_matches(target, str(source)) is False


def test_existing_clone_matches_on_upstream_after_rehome(tmp_path: Path) -> None:
    # After make-it-mine the source lives on `upstream`; a resume must still see
    # the source as present.
    source = _seed_bare_source(tmp_path)
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")
    clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=True,
    )
    assert clone.existing_clone_matches(target, str(source)) is True


def test_origin_is_normalizes_ssh_https(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    target = _clone_into(tmp_path, source, "widgets")
    assert clone.origin_is(target, str(source)) is True
    assert clone.origin_is(target, str(tmp_path / "other.git")) is False


def test_same_repo_normalizes_ghes_ssh_and_https_without_crossing_hosts() -> None:
    assert project_clone_resume.same_repo(
        "git@ghe.example:acme/widgets.git",
        "https://ghe.example/acme/widgets.git",
    ) is True
    assert project_clone_resume.same_repo(
        "git@ghe.example:acme/widgets.git",
        "https://other.example/acme/widgets.git",
    ) is False


# ── _resumable_clone ─────────────────────────────────────────────────────


def test_resumable_clone_clones_an_empty_target(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    target = tmp_path / "checkouts" / "widgets"
    project_onboard._resumable_clone(target, str(source), token=None)
    assert (target / "README.md").is_file()
    assert clone.origin_is(target, str(source))


def test_resumable_clone_skips_an_already_present_clone(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    target = _clone_into(tmp_path, source, "widgets")
    # A sentinel uncommitted file proves the clone was not re-run (which would
    # have refused the non-empty dir or re-cloned over it).
    (target / "WORK_IN_PROGRESS").write_text("x", encoding="utf-8")
    project_onboard._resumable_clone(target, str(source), token=None)
    assert (target / "WORK_IN_PROGRESS").is_file()


def test_resumable_clone_conflict_raises_recovery_message(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    target = tmp_path / "checkouts" / "widgets"
    target.mkdir(parents=True)
    (target / "unrelated.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ProjectOnboardError) as exc:
        project_onboard._resumable_clone(target, str(source), token=None)
    message = str(exc.value)
    # The recovery message names the target and both ways forward.
    assert str(target) in message
    assert "resume" in message.lower()
    assert "start over" in message.lower()


# ── rehome / fork idempotency on a resume ────────────────────────────────


def test_rehome_is_idempotent_on_a_second_run(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    new_origin = tmp_path / "mine.git"
    _git(tmp_path, "init", "--bare", str(new_origin))
    target = _clone_into(tmp_path, source, "widgets")

    first = clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=True,
    )
    # A second run (simulating a resume after the dispatch/install failed) must
    # not error on the already-renamed remote — it re-pushes (a no-op) and
    # returns the same branch.
    second = clone.rehome_to_new_origin(
        target, new_origin_url=str(new_origin),
        default_branch="main", keep_upstream=True,
    )
    assert first == second == "main"
    assert _git(target, "remote", "get-url", "origin") == str(new_origin)
    assert _git(target, "remote", "get-url", "upstream") == str(source)


def test_set_fork_remotes_is_idempotent_on_a_second_run(tmp_path: Path) -> None:
    source = _seed_bare_source(tmp_path)
    fork = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", str(fork))
    target = _clone_into(tmp_path, source, "widgets")

    clone.set_fork_remotes(target, fork_url=str(fork))
    # Second run is a no-op, not an error on the already-renamed remote.
    clone.set_fork_remotes(target, fork_url=str(fork))
    assert _git(target, "remote", "get-url", "origin") == str(fork)
    assert _git(target, "remote", "get-url", "upstream") == str(source)


def test_create_repo_is_idempotent_on_a_second_run(monkeypatch) -> None:
    # The repo-create step resumes: a first run creates the repo, a second run
    # (the prior push hadn't landed) finds the empty repo via 422 and reuses it
    # rather than aborting — so onboarding's last non-idempotent step completes.
    replay = CreateRepoReplay()
    monkeypatch.setattr(github_publish_transport, "_urlopen", replay)

    first = github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="octocat", name="widget", user_login="octocat",
        administration_allowed=True,
    )
    replay.resume_pass()
    second = github_publish.create_repo(
        "https://api.github.com", "ghs_x",
        owner="octocat", name="widget", user_login="octocat",
        administration_allowed=True,
    )

    assert first["full_name"] == second["full_name"] == "octocat/widget"
    assert second["default_branch"] == "main"
    # The fresh create reports reused=False; the 422 resume reports reused=True so
    # the report can tell the user the repo already existed and was reused.
    assert first["reused"] is False
    assert second["reused"] is True


# ── end-to-end: re-run after a partial clone resumes instead of failing ──


def test_import_resumes_over_an_existing_matching_clone(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A `project import` whose target already holds the clone completes (resumes).

    Simulates a prior partial run that cloned the source but failed before the
    dispatch/install steps. The re-run must skip the clone (idempotent) and finish
    — the old behavior hard-failed with "checkout already exists and is not empty".
    """
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    remote = seed_remote(tmp_path)
    checkout = tmp_path / "checkouts" / "imported"
    # Pre-clone the source into the target (the prior partial run's leftover).
    checkout.parent.mkdir(parents=True, exist_ok=True)
    _git(checkout.parent, "clone", str(remote), checkout.name)
    sentinel = checkout / "RESUME_SENTINEL"
    sentinel.write_text("kept across the resume", encoding="utf-8")

    with ProjectOnboardApi(
        project={
            "id": 77, "slug": "imported", "name": "Imported",
            "github_repo": "owner/imported", "default_branch": "trunk",
            "public_item_prefix": "IMP",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main([
            "project", "import", str(remote), str(checkout),
            "--slug", "imported", "--name", "Imported",
            "--github-repo", "owner/imported", "--default-branch", "trunk",
            "--public-item-prefix", "IMP", "--github-adoption", "backlog-only",
            "--config", str(config), "--yes", "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "project.import"
    assert payload["project"]["id"] == 77
    # The pre-existing clone was kept (skipped, not re-cloned over).
    assert sentinel.is_file()
    assert (checkout / ".yoke/install-manifest.json").is_file()
    # The resume signal flows all the way to the report: the report carries a
    # clone_resume block flagging the reused clone, so the rendered onboarding
    # summary can read differently from a fresh run.
    assert payload["clone_resume"]["clone_reused"] is True


def test_fresh_import_carries_no_clone_resume_block(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A first-run `project import` (fresh clone) omits the clone_resume block.

    Mirror of the resume case above: when nothing was reused, the report stays
    byte-identical to the pre-resume-aware shape — no clone_resume key — so only
    a resumed run produces the new resume-aware lines.
    """
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    remote = seed_remote(tmp_path)
    checkout = tmp_path / "checkouts" / "fresh"

    with ProjectOnboardApi(
        project={
            "id": 78, "slug": "fresh", "name": "Fresh",
            "github_repo": "owner/fresh", "default_branch": "trunk",
            "public_item_prefix": "FRS",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main([
            "project", "import", str(remote), str(checkout),
            "--slug", "fresh", "--name", "Fresh",
            "--github-repo", "owner/fresh", "--default-branch", "trunk",
            "--public-item-prefix", "FRS", "--github-adoption", "backlog-only",
            "--config", str(config), "--yes", "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "project.import"
    # A fresh clone reused nothing — no resume block is attached.
    assert "clone_resume" not in payload
