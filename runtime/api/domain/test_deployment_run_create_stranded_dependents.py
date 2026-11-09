"""Creation refuses a release that would strand dependents of an unreleased item.

A carried item merged into the candidate but not yet at its release stage is
skipped, and so is every carried item that depends on it, directly or through
another skipped dependent. Creating that run left the chain for an operator to
attach by hand; creation now refuses by name, and only creation does.
"""

from __future__ import annotations

from runtime.api.domain.deployment_run_create_stranded_dependents_test_support import (
    RELEASE_FLOW as RELEASE_FLOW,
    _candidate as _candidate,
)


from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
)
from yoke_core.domain.deployment_run_create_write import (
    CompositionRefused,
    create_run,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition


UNRELEASED_ID = 9801
DEPENDENT_ID = 9802
TRANSITIVE_ID = 9803
UNRELATED_ID = 9804


def _depend(
    conn: Any, dependent: int, blocker: int, *, gate: str = "integration"
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,"
        "created_at) VALUES (%s,%s,%s,'fact:deployed:stage','test',"
        "'2026-09-14T00:00:00Z')",
        (dependent, blocker, gate),
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


def test_create_enrolls_a_member_whose_closure_blocker_has_not_released(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tip = _candidate(
        test_db,
        tmp_path,
        monkeypatch,
        {UNRELEASED_ID: "implementing", DEPENDENT_ID: "release"},
    )
    _depend(test_db, DEPENDENT_ID, UNRELEASED_ID, gate="closure")

    created = create_run("yoke", RELEASE_FLOW, release_lineage=tip)

    assert [
        row[0]
        for row in test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s",
            (created.run_id,),
        ).fetchall()
    ] == [DEPENDENT_ID]


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
