"""A release attributes the commits its own automation wrote, and only those.

A promotion that rewrites a version pin pushes a commit no backlog item
authored. Left unexplained it is unattributed carried work, and the next
release refuses to compose until somebody records a resolution by hand — so
the run that produced it records it, and attribution reads that record.

What these tests hold down is the ordering and the refusals around it: an
item still wins its own commit, a commit nobody explained still refuses, and
a recording that cannot be proved is named rather than written. A record that
could absorb any commit would waive exactly the delivery proof composition
validation exists to demand.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import (
    deployment_run_carried_work_source,
    deployment_runs,
)
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.deployment_run_release_output_record import (
    OUTCOME_NOTHING_PRODUCED,
    OUTCOME_RECORDED,
    ReleaseOutputRefused,
    record_release_output,
)

ITEM_REF = "YOK-9601"
EMPTY_SOURCES = '{"schema":1,"projects":[],"inputs":{}}'


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A baseline, the pin a release wrote, then unexplained maintenance."""
    repo = tmp_path / "release-output-project"
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
    (repo / "yoke-release-pin.txt").write_text("0.1.1+launch.459\n", encoding="utf-8")
    _git(repo, "add", "yoke-release-pin.txt")
    _git(repo, "commit", "-m", "Pin prod Yoke 0.1.1+launch.459")
    pin = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("maintenance\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Routine maintenance")
    maintenance = _git(repo, "rev-parse", "HEAD")
    return repo, baseline, pin, maintenance


def _flow(conn: Any, flow_id: str, *, binds_own_trunk: bool = False) -> None:
    stages = (
        '[{"name":"complete","input_bindings":'
        '{"trunk_sha":{"project":"%s","branch":"main"}}}]'
        if binds_own_trunk
        else '[{"name":"complete"}]'
    )
    if binds_own_trunk:
        stages = stages % _project_slug(conn)
    conn.execute(
        "INSERT INTO deployment_flows("
        "id,project_id,name,description,stages,created_at,status,"
        "definition_schema_version) "
        "VALUES (%s,1,%s,'',%s,'2026-09-19T00:00:00Z','active',2)",
        (flow_id, flow_id, stages),
    )
    conn.commit()


def _project_slug(conn: Any) -> str:
    row = conn.execute("SELECT slug FROM projects WHERE id=1").fetchone()
    return str(row["slug"] if hasattr(row, "keys") else row[0])


def _run(
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
        (
            run_id,
            flow_id,
            lineage,
            status,
            created_at,
            completed_at,
            EMPTY_SOURCES,
        ),
    )
    conn.commit()


def _carried(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    parsed = parse_carried_work(row["carried_work"])
    assert parsed is not None
    return parsed


@pytest.fixture
def release_source(test_db: Any, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """One repository, one flow, and the run whose promotion wrote the pin."""
    repo, baseline, pin, maintenance = _repository(tmp_path)
    _flow(test_db, "release-output-flow")
    _run(
        test_db,
        "run-release-output-001",
        baseline,
        flow_id="release-output-flow",
        status="succeeded",
        created_at="2026-09-19T00:01:00Z",
        completed_at="2026-09-19T00:02:00Z",
    )
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    return {
        "repo": repo,
        "baseline": baseline,
        "pin": pin,
        "maintenance": maintenance,
        "producer": "run-release-output-001",
        "project": _project_slug(test_db),
    }


def test_a_recorded_pin_commit_composes_without_a_hand_written_resolution(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """The release that wrote the commit is the attribution the next one reads."""
    receipt = record_release_output(
        test_db,
        run_id=release_source["producer"],
        project=release_source["project"],
        commit_sha=release_source["pin"],
    )
    test_db.commit()
    assert receipt["outcome"] == OUTCOME_RECORDED
    _run(
        test_db,
        "run-release-output-002",
        release_source["pin"],
        flow_id="release-output-flow",
        status="executing",
        created_at="2026-09-19T00:03:00Z",
    )

    assert deployment_runs.cmd_update(
        "run-release-output-002", "status", "succeeded"
    ) is None

    carried = _carried(test_db, "run-release-output-002")
    assert carried["commits"] == []
    assert [entry["commit_sha"] for entry in carried["release_output"]] == [
        release_source["pin"]
    ]
    assert carried["release_output"][0]["run_id"] == release_source["producer"]
    assert carried_membership_refusal(test_db, "run-release-output-002") is None


def test_an_unexplained_commit_beside_a_recorded_one_still_refuses(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """Attributing release output waives nothing else in the same range."""
    record_release_output(
        test_db,
        run_id=release_source["producer"],
        project=release_source["project"],
        commit_sha=release_source["pin"],
    )
    test_db.commit()
    _run(
        test_db,
        "run-release-output-003",
        release_source["maintenance"],
        flow_id="release-output-flow",
        status="executing",
        created_at="2026-09-19T00:04:00Z",
    )

    assert deployment_runs.cmd_update(
        "run-release-output-003", "status", "succeeded"
    ) is None

    carried = _carried(test_db, "run-release-output-003")
    assert carried["commits"] == [release_source["maintenance"]]
    refusal = carried_membership_refusal(test_db, "run-release-output-003")
    assert refusal is not None
    assert "1 unattributed carried commit(s)" in refusal


def test_recording_refuses_a_commit_a_backlog_item_already_owns(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """An item's commit is that item's work however the caller labels it."""
    insert_item(
        test_db,
        id=9601,
        project_sequence=9601,
        workflow_id="dash",
        status="done",
    )
    repo = release_source["repo"]
    (repo / "release.txt").write_text("item work\n", encoding="utf-8")
    _git(repo, "commit", "-am", f"Land {ITEM_REF} product changes")
    item_commit = _git(repo, "rev-parse", "HEAD")
    test_db.commit()

    with pytest.raises(ReleaseOutputRefused) as refusal:
        record_release_output(
            test_db,
            run_id=release_source["producer"],
            project=release_source["project"],
            commit_sha=item_commit,
        )

    assert refusal.value.reason == "commit_attributed_to_item"
    assert ITEM_REF in str(refusal.value)


def test_recording_refuses_a_commit_that_predates_the_pinned_source(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """A run cannot have produced a commit its own pinned source already held."""
    _run(
        test_db,
        "run-release-output-004",
        release_source["maintenance"],
        flow_id="release-output-flow",
        status="succeeded",
        created_at="2026-09-19T00:05:00Z",
        completed_at="2026-09-19T00:06:00Z",
    )

    with pytest.raises(ReleaseOutputRefused) as refusal:
        record_release_output(
            test_db,
            run_id="run-release-output-004",
            project=release_source["project"],
            commit_sha=release_source["baseline"],
        )

    assert refusal.value.reason == "commit_precedes_pinned_source"


def test_an_unnamed_commit_resolves_the_branch_the_run_itself_bound(
    test_db: Any, release_source: dict[str, Any]
) -> None:
    """The caller names a project; the flow's own binding names the branch.

    A promotion that pushed nothing leaves that branch where the run pinned
    it, and the receipt says the release produced no commit rather than
    inventing a record for the commit it merely shipped.
    """
    _flow(test_db, "release-output-bound-flow", binds_own_trunk=True)
    _run(
        test_db,
        "run-release-output-005",
        release_source["maintenance"],
        flow_id="release-output-bound-flow",
        status="executing",
        created_at="2026-09-19T00:07:00Z",
    )

    quiet = record_release_output(
        test_db,
        run_id="run-release-output-005",
        project=release_source["project"],
    )
    assert quiet["outcome"] == OUTCOME_NOTHING_PRODUCED
    assert quiet["commit_sha"] == ""

    repo = release_source["repo"]
    (repo / "yoke-release-pin.txt").write_text("0.1.1+launch.460\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Pin prod Yoke 0.1.1+launch.460")
    pushed = _git(repo, "rev-parse", "HEAD")

    recorded = record_release_output(
        test_db,
        run_id="run-release-output-005",
        project=release_source["project"],
    )

    assert recorded["outcome"] == OUTCOME_RECORDED
    assert recorded["commit_sha"] == pushed
