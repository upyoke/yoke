"""A readable comparison puts the omitted-member check back in front of a run.

The membership refusal skips its omitted-member scan whenever the carried-work
derivation reports that its contents are not known, which is the honest thing
to do with an answer nobody computed. It also means a control plane that could
never read the project's source had that check silently disabled on every run
it completed. These tests drive the real deriver against a real repository, so
they fail if the comparison stops being readable rather than passing quietly.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_carried_work_source
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_composition_freeze import (
    carried_membership_refusal,
)
from yoke_core.domain.flow_create import cmd_create


RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "stage",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
)
CARRIED_ITEM_ID = 9401


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path, item_ref: str) -> tuple[Path, str, str]:
    """One baseline release and one landed item, attributable by message."""
    repo = tmp_path / "release-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("landed\n", encoding="utf-8")
    _git(repo, "commit", "-am", f"Land {item_ref} product changes")
    tip = _git(repo, "rev-parse", "HEAD")
    return repo, baseline, tip


def _release_flow(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()
    cmd_create(
        conn,
        "release-admission-flow",
        "yoke",
        "Release admission",
        "",
        RELEASE_STAGES,
        status="disabled",
    )


def _run(conn: Any, run_id: str, *, lineage: str, status: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,created_at,completed_at) "
        "VALUES (%s,1,'release-admission-flow',%s,%s,%s,%s)",
        (run_id, lineage, status, "2026-09-14T00:00:00Z", "2026-09-14T01:00:00Z"),
    )
    conn.commit()


def _delivery_ready_item(conn: Any) -> str:
    insert_item(
        conn,
        id=CARRIED_ITEM_ID,
        project_sequence=CARRIED_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow="release-admission-flow",
    )
    row = conn.execute(
        "SELECT p.public_item_prefix, i.project_sequence FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=%s",
        (CARRIED_ITEM_ID,),
    ).fetchone()
    return f"{row[0]}-{row[1]}"


def test_a_readable_comparison_refuses_a_run_omitting_its_carried_item(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_flow(test_db)
    item_ref = _delivery_ready_item(test_db)
    repo, baseline, tip = _repository(tmp_path, item_ref)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    _run(test_db, "run-previous", lineage=baseline, status="succeeded")
    _run(test_db, "run-candidate", lineage=tip, status="created")

    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["derivation"]["contents_known"] is True
    assert [entry["item_id"] for entry in carried["items"]] == [CARRIED_ITEM_ID]

    refusal = carried_membership_refusal(
        test_db, "run-candidate", carried_work=carried
    )
    assert refusal is not None
    assert "omits delivery-ready carried work" in refusal
    assert item_ref in refusal


def test_an_unreadable_comparison_refuses_by_name_instead_of_scanning(
    test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contents nobody could read still stop the run, naming why.

    This is the branch a hosted completion took on every run: the scan below
    it never executed. It must keep refusing rather than pass, and it must say
    the comparison is the thing that is missing.
    """
    _release_flow(test_db)
    _delivery_ready_item(test_db)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )
    _run(test_db, "run-previous", lineage="a" * 40, status="succeeded")
    _run(test_db, "run-candidate", lineage="b" * 40, status="created")

    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["derivation"]["contents_known"] is False
    assert carried["derivation"]["status"] == "unknown"

    refusal = carried_membership_refusal(
        test_db, "run-candidate", carried_work=carried
    )
    assert refusal is not None
    assert "carried-code membership is project_source_unavailable" in refusal
