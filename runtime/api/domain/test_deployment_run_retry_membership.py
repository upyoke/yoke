"""Retrying a failed candidate keeps the items that candidate delivers.

A retry re-runs one revision that already failed. Creating it without the
membership of the run it retries silently converts an item-bound release into
an environment-level one, and the item it was recovering can never satisfy its
own completion gate no matter how often its deployment succeeds afterwards.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request as _request,
)
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import deployment_runs

#: Where the create handler reads the project deploy lock. Holding it is a
#: separate gate from the membership these tests are about.
DEPLOY_LOCK = "yoke_core.domain.handlers.deployment_run_creation.deploy_lock_refusal"

LINEAGE = "a" * 40
SNAPSHOT = json.dumps({"schema": 1, "requirement_ids": [7]})
SELECTION = json.dumps({"schema": 1, "plan_ids": [], "requirement_ids": [7]})


@pytest.fixture
def retry_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        from yoke_core.domain.deployment_runs_schema import cmd_init

        cmd_init(db_path)
        yield db_path


def _failed_run(db_path: str, *, run_id: str, member_ids: tuple[int, ...]) -> None:
    conn = connect_test_db(db_path)
    try:
        insert_deployment_run(
            conn,
            id=run_id,
            flow="retry-flow",
            status="failed",
            current_stage="deploy",
            release_lineage=LINEAGE,
            completed_at=iso8601_now(),
        )
        for item_id in member_ids:
            insert_item(conn, id=item_id, workflow_id="dash", status="reviewing-implementation")
            conn.execute(
                "INSERT INTO deployment_run_items (run_id, item_id, added_at, "
                "delivery_intent, requirement_selection, requirement_snapshot) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (run_id, item_id, iso8601_now(), "final", SELECTION, SNAPSHOT),
            )
        conn.commit()
    finally:
        conn.close()


def _runs(db_path: str) -> list[str]:
    conn = connect_test_db(db_path)
    try:
        return [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM deployment_runs ORDER BY id"
            ).fetchall()
        ]
    finally:
        conn.close()


def _members(db_path: str, run_id: str) -> list[tuple]:
    conn = connect_test_db(db_path)
    try:
        return [
            tuple(row)
            for row in conn.execute(
                "SELECT item_id, delivery_intent, requirement_selection, "
                "requirement_snapshot FROM deployment_run_items "
                "WHERE run_id=%s ORDER BY item_id",
                (run_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _create(payload: dict):
    with patch(DEPLOY_LOCK, return_value=None):
        return deployment_runs.handle_deployment_run_create(
            _request(function="deployment_runs.create", payload=payload),
        )


def test_a_retry_carries_the_frozen_membership_of_the_run_it_retries(
    retry_db_path: str,
):
    _failed_run(retry_db_path, run_id="run-failed-a", member_ids=(4101, 4102))

    outcome = _create(
        {"project": "yoke", "flow": "retry-flow", "retry_of": "run-failed-a"}
    )

    assert outcome.primary_success, outcome.error
    retry_id = outcome.result_payload["run_id"]
    assert outcome.result_payload["retry_of"] == "run-failed-a"
    assert outcome.result_payload["inherited_item_ids"] == [4101, 4102]
    # The selection and the snapshot travel with the candidate: they say what
    # this release must still prove, not what an earlier run proved.
    assert _members(retry_db_path, retry_id) == [
        (4101, "final", SELECTION, SNAPSHOT),
        (4102, "final", SELECTION, SNAPSHOT),
    ]
    assert outcome.result_payload["release_lineage"] == LINEAGE


def test_an_environment_level_retry_stays_environment_level(retry_db_path: str):
    """An empty copy is the right answer, not a reason to find membership."""
    _failed_run(retry_db_path, run_id="run-failed-b", member_ids=())

    outcome = _create(
        {"project": "yoke", "flow": "retry-flow", "retry_of": "run-failed-b"}
    )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["inherited_item_ids"] == []
    assert _members(retry_db_path, outcome.result_payload["run_id"]) == []


def test_retrying_a_different_candidate_is_refused_as_a_replacement(
    retry_db_path: str,
):
    """Inheriting membership is only sound while the candidate is identical."""
    _failed_run(retry_db_path, run_id="run-failed-c", member_ids=(4103,))

    outcome = _create(
        {
            "project": "yoke",
            "flow": "retry-flow",
            "retry_of": "run-failed-c",
            "release_lineage": "b" * 40,
        }
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "retry_candidate_mismatch"
    assert "start a new run" in outcome.error.message


def test_a_fresh_run_inherits_nothing(retry_db_path: str):
    _failed_run(retry_db_path, run_id="run-failed-d", member_ids=(4104,))

    outcome = _create(
        {"project": "yoke", "flow": "retry-flow", "release_lineage": LINEAGE}
    )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["retry_of"] is None
    assert _members(retry_db_path, outcome.result_payload["run_id"]) == []


def test_a_membership_copy_failure_leaves_no_usable_empty_retry(
    retry_db_path: str,
):
    """The recovery must not reintroduce the defect it recovers from.

    A run committed before its membership is copied survives the copy failing,
    and a member-less item-bound run is exactly what can never reach its own
    completion gate — so the two writes are one transaction and a failure
    leaves no run behind at all.
    """
    _failed_run(retry_db_path, run_id="run-failed-e", member_ids=(4105,))
    before = _runs(retry_db_path)

    boom = RuntimeError("membership copy failed mid-transaction")
    with patch(
        "yoke_core.domain.deployment_run_create_write.copy_frozen_members",
        side_effect=boom,
    ):
        with pytest.raises(RuntimeError, match="membership copy failed"):
            _create(
                {"project": "yoke", "flow": "retry-flow", "retry_of": "run-failed-e"}
            )

    assert _runs(retry_db_path) == before
