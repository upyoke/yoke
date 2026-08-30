"""Completed deployment runs retain inert carried-work attribution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_carried_work, deployment_runs
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION


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


def test_itemless_success_records_items_and_bare_commits(
    test_db: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, base, item_commit, evidence_commit, bare_commit = _repository(tmp_path)
    _flow(test_db)
    insert_item(
        test_db,
        id=9101,
        project_sequence=9041,
        workflow_id="dash",
        status="implemented",
    )
    insert_item(
        test_db,
        id=9103,
        project_sequence=9043,
        workflow_id="dash",
        status="implemented",
    )
    _run(
        test_db,
        "run-carried-001",
        base,
        status="succeeded",
        created_at="2026-08-30T00:01:00Z",
        completed_at="2026-08-30T00:02:00Z",
    )
    _run(
        test_db,
        "run-carried-002",
        bare_commit,
        status="executing",
        created_at="2026-08-30T00:03:00Z",
    )
    test_db.execute(
        "INSERT INTO events("
        "event_id,source_type,session_id,severity,event_kind,event_type,"
        "event_name,service,project_id,item_id,envelope,created_at) "
        "VALUES ('carried-receipt','system','test','INFO','lifecycle',"
        "'merge_lifecycle','StandaloneMergeReceiptRecorded','cli',1,'9101',"
        "%s,'2026-08-30T00:02:30Z')",
        (json.dumps({"context": {"merge_sha": item_commit}}),),
    )
    test_db.execute(
        "INSERT INTO item_sections("
        "item_id,section_name,content,ordering,source,created_at,updated_at) "
        "VALUES (9103,%s,%s,190,'direct-workflow',%s,%s)",
        (
            DASH_EVIDENCE_SECTION,
            json.dumps({"merge_sha": evidence_commit}),
            "2026-08-30T00:02:30Z",
            "2026-08-30T00:02:30Z",
        ),
    )
    test_db.commit()
    monkeypatch.setattr(
        deployment_run_carried_work,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    error = deployment_runs.cmd_update(
        "run-carried-002",
        "status",
        "succeeded",
    )

    assert error is None
    carried = _stored(test_db, "run-carried-002")
    assert carried["derivation"]["reason"] == "partial_item_resolution"
    assert carried["items"] == [
        {
            "item_id": 9101,
            "ref": "YOK-9041",
            "commit_shas": [item_commit],
        },
        {
            "item_id": 9103,
            "ref": "YOK-9043",
            "commit_shas": [evidence_commit],
        },
    ]
    assert carried["commits"] == [bare_commit]
    members = test_db.execute(
        "SELECT COUNT(*) AS n FROM deployment_run_items WHERE run_id='run-carried-002'"
    ).fetchone()
    assert members["n"] == 0


def test_first_item_bound_run_records_empty_without_touching_item_lifecycle(
    test_db: Any,
) -> None:
    _flow(test_db)
    insert_item(
        test_db,
        id=9102,
        project_sequence=9042,
        workflow_id="dash",
        status="release",
    )
    _run(
        test_db,
        "run-carried-003",
        "a" * 40,
        status="executing",
        created_at="2026-08-30T00:04:00Z",
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-carried-003',9102,'2026-08-30T00:04:00Z')"
    )
    test_db.commit()

    error = deployment_runs.cmd_update(
        "run-carried-003",
        "status",
        "succeeded",
    )

    assert error is None
    carried = _stored(test_db, "run-carried-003")
    assert carried["derivation"]["reason"] == "no_prior_succeeded_run"
    assert carried["items"] == []
    assert carried["commits"] == []
    item = test_db.execute("SELECT status FROM items WHERE id=9102").fetchone()
    assert item["status"] == "release"


def test_unreachable_prior_lineage_records_named_empty_result(
    test_db: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, _base, _item_commit, _evidence_commit, head = _repository(tmp_path)
    _flow(test_db)
    _run(
        test_db,
        "run-carried-004",
        "f" * 40,
        status="succeeded",
        created_at="2026-08-30T00:05:00Z",
        completed_at="2026-08-30T00:06:00Z",
    )
    _run(
        test_db,
        "run-carried-005",
        head,
        status="executing",
        created_at="2026-08-30T00:07:00Z",
    )
    monkeypatch.setattr(
        deployment_run_carried_work,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )

    error = deployment_runs.cmd_update(
        "run-carried-005",
        "status",
        "succeeded",
    )

    assert error is None
    carried = _stored(test_db, "run-carried-005")
    assert carried["derivation"]["reason"] == "prior_release_lineage_unreachable"
    assert carried["items"] == []
    assert carried["commits"] == []
