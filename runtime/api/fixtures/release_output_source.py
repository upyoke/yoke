"""A repository, flow and run helpers for release-output checks.

Release-output behaviour is only meaningful against a real comparison — the
guards ask git whether one commit descends from another, and attribution asks
the same resolver the deriver uses. Tests that stubbed either would pass while
the thing they protect quietly stopped working, so these helpers build an
actual repository and actual runs over it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from yoke_core.domain.deployment_run_carried_work import parse_carried_work


#: A run that recorded no bindings still recorded that it had none, which is
#: what distinguishes a started run from one that has not resolved its sources.
EMPTY_SOURCES = '{"schema":1,"projects":[],"inputs":{}}'


def git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return its trimmed stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def release_output_repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A baseline, the pin a release wrote, then unexplained maintenance."""
    repo = tmp_path / "release-output-project"
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
    (repo / "yoke-release-pin.txt").write_text("0.1.1+launch.459\n", encoding="utf-8")
    git(repo, "add", "yoke-release-pin.txt")
    git(repo, "commit", "-m", "Pin prod Yoke 0.1.1+launch.459")
    pin = git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("maintenance\n", encoding="utf-8")
    git(repo, "commit", "-am", "Routine maintenance")
    return repo, baseline, pin, git(repo, "rev-parse", "HEAD")


def project_slug(conn: Any) -> str:
    row = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()
    return str(row["slug"] if hasattr(row, "keys") else row[0])


def insert_flow(conn: Any, flow_id: str, *, binds_own_trunk: bool = False) -> None:
    """One v2 flow, optionally binding this same project's trunk branch."""
    stages = '[{"name":"complete"}]'
    if binds_own_trunk:
        stages = (
            '[{"name":"complete","input_bindings":'
            '{"trunk_sha":{"project":"%s","branch":"main"}}}]' % project_slug(conn)
        )
    conn.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status,"
        "definition_schema_version) "
        "VALUES (%s,1,%s,'',%s,'2026-09-19T00:00:00Z','active',2)",
        (flow_id, flow_id, stages),
    )
    conn.commit()


def insert_run(
    conn: Any,
    run_id: str,
    lineage: str,
    *,
    flow_id: str,
    status: str,
    created_at: str,
    completed_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "completed_at,bound_sources) "
        "VALUES (%s,1,%s,%s,%s,'complete',%s,%s,%s)",
        (run_id, flow_id, lineage, status, created_at, completed_at, EMPTY_SOURCES),
    )
    conn.commit()


def carried_work_of(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    parsed = parse_carried_work(row["carried_work"])
    assert parsed is not None
    return parsed


__all__ = [
    "EMPTY_SOURCES",
    "carried_work_of",
    "git",
    "insert_flow",
    "insert_run",
    "project_slug",
    "release_output_repository",
]
