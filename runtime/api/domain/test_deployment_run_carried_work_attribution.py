"""A release names the work that produced its commits, and nothing else.

Attribution reaches for a branch when the recorded lineage does not cover a
commit, and a branch is a weak signal: a lane created from the trunk points at
whatever the trunk was on and has committed nothing of its own. Reading such a
branch — through a commit's ref decoration or through an item's lane row —
credits a neighbour's release to work that has not shipped.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_carried_work, deployment_runs
from yoke_core.domain.deployment_run_carried_work import parse_carried_work


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("item\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Ship product changes")
    item_commit = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("evidence\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Ship evidence-backed changes")
    evidence_commit = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("bare\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Routine maintenance")
    bare_commit = _git(repo, "rev-parse", "HEAD")
    return repo, base, item_commit, evidence_commit, bare_commit


def _flow(conn: Any) -> None:
    conn.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status) "
        "VALUES ('carried-work-flow',1,'Carried work','',"
        "'[{\"name\":\"complete\"}]','2026-08-30T00:00:00Z','active')"
    )
    conn.commit()


def _run(
    conn: Any,
    run_id: str,
    lineage: str,
    *,
    status: str,
    created_at: str,
    completed_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,current_stage,created_at,"
        "completed_at) VALUES (%s,1,'carried-work-flow',%s,%s,'complete',%s,%s)",
        (run_id, lineage, status, created_at, completed_at),
    )
    conn.commit()


def _stored(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    parsed = parse_carried_work(row["carried_work"])
    assert parsed is not None
    return parsed


def test_an_open_lane_forked_from_the_trunk_carries_nothing(
    test_db: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An unlanded item's branch points at somebody else's release commit.

    A lane created from the trunk has no commits of its own until the work is
    written, so resolving its branch name reaches whatever the trunk was
    pointing at — reading that as the item's contribution attributes a
    neighbour's release to work that has not shipped.
    """
    repo, base, item_commit, _evidence_commit, bare_commit = _repository(tmp_path)
    _flow(test_db)
    insert_item(
        test_db,
        id=9111,
        project_sequence=9051,
        workflow_id="dash",
        status="implementing",
    )
    test_db.execute(
        "INSERT INTO item_worktrees("
        "item_id,branch,path,lane_role,state,created_at,updated_at) "
        "VALUES (9111,'YOK-9051','/lane','implementation','active',"
        "'2026-08-30T00:01:00Z','2026-08-30T00:01:00Z')"
    )
    # The lane branch was created from the trunk after the release commit and
    # has committed nothing, so it still points there.
    _git(repo, "branch", "YOK-9051", item_commit)
    _run(
        test_db,
        "run-open-lane-001",
        base,
        status="succeeded",
        created_at="2026-08-30T00:01:00Z",
        completed_at="2026-08-30T00:02:00Z",
    )
    _run(
        test_db,
        "run-open-lane-002",
        bare_commit,
        status="executing",
        created_at="2026-08-30T00:03:00Z",
    )
    test_db.commit()
    monkeypatch.setattr(
        deployment_run_carried_work,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    error = deployment_runs.cmd_update(
        "run-open-lane-002", "status", "succeeded",
    )

    assert error is None
    carried = _stored(test_db, "run-open-lane-002")
    assert [entry["item_id"] for entry in carried["items"]] == []
    assert item_commit in carried["commits"]


def test_a_cancelled_item_holding_an_open_lane_carries_nothing(
    test_db: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The same borrowed-branch reach through the item-metadata pass.

    An item that carries a resolution reference is read for merge metadata
    even though it never landed. Resolving its still-open lane branch would
    reach the trunk commit the lane forked from, so the branch is only
    consulted once the item has actually landed.
    """
    repo, base, item_commit, _evidence_commit, bare_commit = _repository(tmp_path)
    _flow(test_db)
    insert_item(
        test_db,
        id=9121,
        project_sequence=9061,
        workflow_id="dash",
        status="cancelled",
        resolution_ref="superseded",
    )
    test_db.execute(
        "INSERT INTO item_worktrees("
        "item_id,branch,path,lane_role,state,created_at,updated_at) "
        "VALUES (9121,'lane-9061','/lane','implementation','active',"
        "'2026-08-30T00:01:00Z','2026-08-30T00:01:00Z')"
    )
    _git(repo, "branch", "lane-9061", item_commit)
    _run(
        test_db,
        "run-cancelled-lane-001",
        base,
        status="succeeded",
        created_at="2026-08-30T00:01:00Z",
        completed_at="2026-08-30T00:02:00Z",
    )
    _run(
        test_db,
        "run-cancelled-lane-002",
        bare_commit,
        status="executing",
        created_at="2026-08-30T00:03:00Z",
    )
    test_db.commit()
    monkeypatch.setattr(
        deployment_run_carried_work,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    error = deployment_runs.cmd_update(
        "run-cancelled-lane-002", "status", "succeeded",
    )

    assert error is None
    carried = _stored(test_db, "run-cancelled-lane-002")
    assert [entry["item_id"] for entry in carried["items"]] == []
