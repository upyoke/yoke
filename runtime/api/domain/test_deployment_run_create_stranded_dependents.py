"""Creation refuses a release that would strand dependents of an unreleased item.

A carried item merged into the candidate but not yet at its release stage is
skipped, and so is every carried item that depends on it, directly or through
another skipped dependent. Creating that run left the chain for an operator to
attach by hand; creation now refuses by name, and only creation does.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_run_create_write import (
    CompositionRefused,
    create_run,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.flow_create import cmd_create


RELEASE_FLOW = "stranded-dependents-flow"
UNRELEASED_ID = 9801
DEPENDENT_ID = 9802
TRANSITIVE_ID = 9803
UNRELATED_ID = 9804


def _candidate(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statuses: dict[int, str],
) -> tuple[dict[int, str], str]:
    """Dash items carried by one landing, and the candidate commit."""
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        json.dumps(
            [
                {
                    "name": "stage",
                    "step_runner": "auto",
                    "stage_kind": "execution",
                    "scope": "run",
                }
            ]
        ),
        target_tier="ephemeral",
    )
    for item_id, status in statuses.items():
        insert_item(
            conn,
            id=item_id,
            project_sequence=item_id,
            workflow_id="dash",
            status=status,
            deployment_flow=RELEASE_FLOW,
            merged_at="2026-09-14T00:10:00Z",
        )
    conn.commit()
    refs = {item_id: item_ref(conn, item_id) for item_id in statuses}
    repo, baseline, tip = release_repository(tmp_path, "stranded")
    for item_id, ref in refs.items():
        record_landing_receipt(conn, item_id, branch=ref, tip=tip)
    serve_repository(monkeypatch, repo)
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=RELEASE_FLOW
    )
    return refs, tip


def _depend(conn: Any, dependent: int, blocker: int) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,"
        "created_at) VALUES (%s,%s,'closure','fact:deployed:stage','test',"
        "'2026-09-14T00:00:00Z')",
        (dependent, blocker),
    )
    conn.commit()


def _run_ids(conn: Any) -> list[str]:
    rows = conn.execute("SELECT id FROM deployment_runs ORDER BY id").fetchall()
    return [str(row[0]) for row in rows]


def _member_rows(conn: Any) -> int:
    return int(conn.execute("SELECT count(*) FROM deployment_run_items").fetchone()[0])


def _composition_notice(run_id: str) -> str:
    """What composition reports for a run creation committed."""
    ok, message = cmd_validate_composition(run_id)
    assert ok is True, message
    return message


def test_create_refuses_when_an_unreleased_item_strands_its_dependents(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs, tip = _candidate(
        test_db,
        tmp_path,
        monkeypatch,
        {
            UNRELEASED_ID: "implementing",
            DEPENDENT_ID: "release",
            TRANSITIVE_ID: "release",
            UNRELATED_ID: "release",
        },
    )
    _depend(test_db, DEPENDENT_ID, UNRELEASED_ID)
    _depend(test_db, TRANSITIVE_ID, DEPENDENT_ID)

    with pytest.raises(CompositionRefused) as refused:
        create_run("yoke", RELEASE_FLOW, release_lineage=tip)

    message = str(refused.value)
    assert "release_stranding_unreleased_blocker" in message
    assert (
        f"{refs[UNRELEASED_ID]} (status=implementing) strands "
        f"{refs[DEPENDENT_ID]}, {refs[TRANSITIVE_ID]}"
    ) in message
    assert f"strands {refs[DEPENDENT_ID]}, {refs[TRANSITIVE_ID]}." in message
    assert "reaches its release stage, then retry" in message
    assert "yoke deployment-runs create" in message
    assert _run_ids(test_db) == ["run-previous"]
    assert _member_rows(test_db) == 0


def test_create_warns_when_no_carried_item_depends_on_the_unreleased_item(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs, tip = _candidate(
        test_db,
        tmp_path,
        monkeypatch,
        {UNRELEASED_ID: "implementing", UNRELATED_ID: "release"},
    )

    created = create_run("yoke", RELEASE_FLOW, release_lineage=tip)

    assert created.run_id in _run_ids(test_db)
    notice = _composition_notice(created.run_id)
    assert "WARNING: merged into this candidate but not at release yet" in notice
    assert f"{refs[UNRELEASED_ID]} (status=implementing)" in notice
    assert "release_stranding_unreleased_blocker" not in notice


def test_validating_an_existing_run_keeps_the_notice_instead_of_refusing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs, tip = _candidate(
        test_db,
        tmp_path,
        monkeypatch,
        {UNRELEASED_ID: "implementing", DEPENDENT_ID: "release"},
    )
    _depend(test_db, DEPENDENT_ID, UNRELEASED_ID)
    insert_run(
        test_db, "run-candidate", lineage=tip, status="created", flow=RELEASE_FLOW
    )

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is True, message
    assert "release_stranding_unreleased_blocker" not in message
    assert f"{refs[DEPENDENT_ID]} blocked by {refs[UNRELEASED_ID]}" in message
    assert "WARNING: merged into this candidate but not at release yet" in message
