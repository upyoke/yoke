"""A real repository and run pair for carried-work tests.

Carried-work behaviour is only meaningful against an actual comparison, so
these helpers build one: a baseline release commit, a second commit whose
message attributes it to an item, and two runs pinned to those two lineages.
Tests that stubbed the deriver instead would pass while the comparison that
feeds enrollment and its refusals quietly stopped being readable.
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


def release_repository(tmp_path: Path, item_ref: str) -> tuple[Path, str, str]:
    """One baseline release and one landed item, attributable by message."""
    repo = tmp_path / "release-project"
    repo.mkdir()
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
    git(repo, "commit", "-am", f"Land {item_ref} product changes")
    return repo, baseline, git(repo, "rev-parse", "HEAD")


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
) -> None:
    """Insert one deployment run pinned to ``lineage``."""
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,created_at,completed_at) "
        "VALUES (%s,1,%s,%s,%s,%s,%s)",
        (run_id, flow, lineage, status, "2026-09-14T00:00:00Z",
         "2026-09-14T01:00:00Z"),
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
