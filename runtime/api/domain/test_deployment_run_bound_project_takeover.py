"""A release shipping past a bound project's never-started run supersedes it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run
from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    CONSUMER_FLOW,
    CONSUMER_ITEM_ID,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git
from yoke_core.domain import deployment_run_create_composition as composition
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody

STALE = "run-consumer-never-started"
CREATOR = "release-creating-session"


def _environment(conn: Any, project_id: int, name: str) -> int:
    site = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES(%s,'Fixture site','2026-09-14T00:00:00Z') RETURNING id",
        (project_id,),
    ).fetchone()[0]
    return int(
        conn.execute(
            "INSERT INTO environments(site,project_id,name,created_at) "
            "VALUES(%s,%s,%s,'2026-09-14T00:00:00Z') "
            "ON CONFLICT(project_id,name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
            (site, project_id, name),
        ).fetchone()[0]
    )


def _stale_consumer_run(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """A never-started consumer run holds the consumer item; trunk then moves on."""
    release = two_project_release(
        conn, tmp_path, monkeypatch, consumer_status="release"
    )
    carrier_env = _environment(conn, 1, "prod")
    consumer_env = _environment(conn, release["consumer_id"], "prod")
    insert_deployment_run(
        conn,
        id=STALE,
        project_id=release["consumer_id"],
        flow=CONSUMER_FLOW,
        status="created",
        release_lineage=release["consumer_tip"],
        target_tier="persistent",
        target_environment_id=consumer_env,
        created_at="2026-09-14T00:30:00Z",
    )
    # The consumer item merged and waits for its release.
    conn.execute(
        "UPDATE items SET merged_at='2026-09-14T00:20:00Z' WHERE id=%s",
        (CONSUMER_ITEM_ID,),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES(%s,%s,'2026-09-14T00:30:00Z')",
        (STALE, CONSUMER_ITEM_ID),
    )
    conn.commit()
    repo = release["consumer_repo"]
    (repo / "later.txt").write_text("a later consumer commit\n", encoding="utf-8")
    git(repo, "add", "later.txt")
    git(repo, "commit", "-m", "Later consumer work")
    release["consumer_later"] = git(repo, "rev-parse", "HEAD")
    for module in (composition, create_write):
        # The fixture flows are disabled definitions; creation itself is real.
        monkeypatch.setattr(
            module, "run_target", lambda *_args: ("persistent", carrier_env)
        )
        monkeypatch.setattr(module, "refuse_run_that_cannot_execute", lambda *_: None)
    return release


def _members(conn: Any, run_id: str) -> set[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchall()
    return {int(row[0]) for row in rows}


def _create(conn: Any) -> str:
    lineage = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    return create_write.create_run(
        "yoke", CARRIER_FLOW, release_lineage=lineage, session_id=CREATOR
    ).run_id


def test_release_carrying_a_later_commit_supersedes_the_stale_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = _stale_consumer_run(test_db, tmp_path, monkeypatch)

    created = _create(test_db)

    pinned = test_db.execute(
        "SELECT bound_sources FROM deployment_runs WHERE id=%s", (created,)
    ).fetchone()[0]
    assert release["consumer_later"] in pinned
    assert CONSUMER_ITEM_ID in _members(test_db, created)
    assert CONSUMER_ITEM_ID not in _members(test_db, STALE)
    stale = test_db.execute(
        "SELECT status,superseded_by_run_id FROM deployment_runs WHERE id=%s", (STALE,)
    ).fetchone()
    assert (stale["status"], stale["superseded_by_run_id"]) == ("cancelled", created)
    (removal,) = [
        record
        for record in membership_removals(test_db, STALE)
        if int(record["item_id"]) == CONSUMER_ITEM_ID
    ]
    assert removal["transferred_to_run_id"] == created
    assert f"taken over by run {created}, which ships project" in removal["reason"]
    assert release["consumer_later"] in removal["reason"]


def test_a_stale_run_with_a_live_driver_keeps_its_hold_and_is_named(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stale_consumer_run(test_db, tmp_path, monkeypatch)
    attach_driver(
        test_db, STALE, session_id="stale-run-driver", pid=4343, phase=PHASE_EXECUTING
    )
    test_db.commit()

    created = _create(test_db)

    stale = test_db.execute(
        "SELECT status,superseded_by_run_id FROM deployment_runs WHERE id=%s", (STALE,)
    ).fetchone()
    assert (stale["status"], stale["superseded_by_run_id"]) == ("created", None)
    assert CONSUMER_ITEM_ID in _members(test_db, STALE)
    assert CONSUMER_ITEM_ID not in _members(test_db, created)
    held = {record.item_id: record.run_id for record in candidate_custody(test_db, created).held}
    assert held[CONSUMER_ITEM_ID] == STALE
