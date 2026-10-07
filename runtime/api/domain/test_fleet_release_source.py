"""A release-time fleet rehearsal runs exactly the release commit's code."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import deploy_pipeline_fleet_release_source as release_source
from yoke_core.domain import migrations as history_package
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.schema_shape_source import digest_schema_shape

_MODULES = "history"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def engine_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repository whose history directory is byte-identical to the engine's."""
    repo = tmp_path / "repo"
    (repo / _MODULES).mkdir(parents=True)
    _git(repo, "init", "-q")
    for entry in ordered_entries(history_dir(history_package)):
        shutil.copyfile(entry.path, repo / _MODULES / entry.path.name)
    return repo, _commit(repo, "release")


def _names() -> tuple[str, ...]:
    return tuple(e.name for e in ordered_entries(history_dir(history_package)))


def test_identical_engine_source_may_rehearse_for_the_release(engine_repo) -> None:
    repo, sha = engine_repo
    assert (
        release_source.engine_source_mismatch(
            str(repo), sha, _MODULES, _names(), digest_schema_shape()
        )
        == ""
    )


def test_engine_differing_from_the_release_commit_is_refused(engine_repo) -> None:
    repo, _sha = engine_repo
    first = sorted((repo / _MODULES).glob("[0-9]*.py"))[0]
    first.write_text(first.read_text() + "\n# changed at release\n")
    changed = _commit(repo, "release with a changed entry")

    mismatch = release_source.engine_source_mismatch(
        str(repo), changed, _MODULES, _names(), digest_schema_shape()
    )

    assert first.stem in mismatch
    assert "release driver from the release commit" in mismatch


def test_shifted_schema_shape_is_refused(engine_repo) -> None:
    repo, sha = engine_repo
    mismatch = release_source.engine_source_mismatch(
        str(repo), sha, _MODULES, _names(), "0" * 64
    )
    assert "schema shape differs" in mismatch


def test_release_checkout_is_the_commit_not_the_working_tree(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    (repo / _MODULES).mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / _MODULES / "0001_entry.py").write_text("RELEASED = True\n")
    sha = _commit(repo, "release")
    (repo / _MODULES / "0001_entry.py").write_text("RELEASED = False\n")
    (repo / _MODULES / "0002_later.py").write_text("LATER = True\n")

    with release_source.release_checkout(str(repo), sha) as checkout:
        assert (
            checkout / _MODULES / "0001_entry.py"
        ).read_text() == "RELEASED = True\n"
        assert not (checkout / _MODULES / "0002_later.py").exists()
    assert not checkout.exists()


def test_unknown_release_commit_names_the_recovery(tmp_path: Path) -> None:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "f").write_text("x")
    _commit(repo, "only")

    with pytest.raises(release_source.ReleaseSourceError, match="Fetch the commit"):
        with release_source.release_checkout(str(repo), "f" * 40):
            pass
