"""A real repository and run pair for carried-work tests.

Carried-work behaviour is only meaningful against an actual comparison, so
these helpers build one: a baseline release commit, a second commit for the
landing, and two runs pinned to those two lineages. Tests that stubbed the
deriver instead would pass while the comparison that feeds enrollment and its
refusals quietly stopped being readable.

The landing commit names its item in the message by default. A caller that is
testing a different attribution rung — a receipt, a lane head — passes
``names_item=False`` so the message attributes nothing and only that rung can
answer.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yoke_core.domain import deployment_run_carried_work_source


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return its trimmed stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def release_repository(
    tmp_path: Path,
    item_ref: str,
    *,
    name: str = "release-project",
    names_item: bool = True,
) -> tuple[Path, str, str]:
    """One baseline release and one landed item.

    With ``names_item`` the landing commit message carries the item
    reference, which is the message rung attribution reads first among the
    commit-text sources. Without it the message attributes nothing, leaving
    the recorded evidence rungs to answer alone.
    """
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(repo, "config", "user.name", "Yoke Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "release.txt")
    git(repo, "commit", "-m", "Release baseline")
    baseline = git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("landed\n", encoding="utf-8")
    subject = (
        f"Land {item_ref} product changes" if names_item else "Land product changes"
    )
    git(repo, "commit", "-am", subject)
    return repo, baseline, git(repo, "rev-parse", "HEAD")


def bound_source_repository(
    tmp_path: Path, name: str, item_ref: str, *, names_item: bool = True
) -> tuple[Path, str, str]:
    """A second project's repository, reachable as its own ``origin``.

    A bound branch is resolved the way the deploy driver resolves it — by
    asking the checkout's remote what the branch names now — so the fixture
    gives the repository a real origin instead of stubbing the read.
    """
    repo, baseline, tip = release_repository(
        tmp_path, item_ref, name=name, names_item=names_item
    )
    git(repo, "remote", "add", "origin", str(repo))
    return repo, baseline, tip


def serve_repositories(
    monkeypatch: pytest.MonkeyPatch, repos: dict[int, Path]
) -> None:
    """Map each project id to the checkout this machine holds for it."""
    from yoke_core.domain import project_checkout_locations

    def lookup(project_id: Any, **_kwargs: Any) -> Path | None:
        return repos.get(int(project_id)) if project_id is not None else None

    monkeypatch.setattr(
        deployment_run_carried_work_source, "checkout_for_project_id", lookup
    )
    monkeypatch.setattr(
        project_checkout_locations, "checkout_for_project_id", lookup
    )


def serve_repository(
    monkeypatch: pytest.MonkeyPatch, repo: Path | None
) -> None:
    """Point carried-work derivation at ``repo``, or at no checkout at all."""
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )


def insert_run(
    conn: Any,
    run_id: str,
    *,
    lineage: str,
    status: str,
    flow: str,
    project_id: int = 1,
    bound_sources: str | None = None,
    completed_at: str = "2026-09-14T01:00:00Z",
) -> None:
    """Insert one deployment run pinned to ``lineage``.

    ``bound_sources`` is the record a started run writes for every project it
    ships but does not own; a test that needs a predecessor to have carried
    such a project supplies it directly rather than starting a whole run.
    """
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,bound_sources,status,created_at,"
        "completed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (run_id, project_id, flow, lineage, bound_sources, status,
         "2026-09-14T00:00:00Z", completed_at),
    )
    conn.commit()


def item_ref(conn: Any, item_id: int) -> str:
    """Render one item's public reference from its stored project prefix."""
    row = conn.execute(
        "SELECT p.public_item_prefix, i.project_sequence FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=%s",
        (int(item_id),),
    ).fetchone()
    return f"{row[0]}-{row[1]}"


def stage_environment(conn: Any) -> None:
    """Give the project the stage environment a persistent flow resolves."""
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()
