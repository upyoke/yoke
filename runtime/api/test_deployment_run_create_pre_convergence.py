"""Keyed deployment-run creation before the key columns converge.

A self-deploy creates its production run from a driver already at the new
release against a database the old release still serves, so the additive
``create_idempotency_key`` / ``create_request`` columns do not exist yet.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_create_idempotency import (
    BASIS_UNCONVERGED_REQUEST_MATCH,
    UnconvergedReplayAmbiguous,
    canonical_request,
    replay_run,
)
from yoke_core.domain.deployment_run_create_write import create_run

pytest_plugins = ["runtime.api.deployment_runs_test_db"]

LINEAGE = "a" * 40


@pytest.fixture
def unconverged_db(db_path: str) -> str:
    conn = connect_test_db(db_path)
    try:
        conn.execute("ALTER TABLE deployment_runs DROP COLUMN create_idempotency_key")
        conn.execute("ALTER TABLE deployment_runs DROP COLUMN create_request")
        conn.commit()
    finally:
        conn.close()
    return db_path


def _create(db_path: str, key: str = "release-1", **kwargs):
    request = canonical_request(
        {"project": "yoke", "flow": "flow-main", "created_by": "operator", **kwargs}
    )
    return create_run(
        "yoke",
        "flow-main",
        db_path=db_path,
        idempotency_key=key,
        create_request=request,
        **kwargs,
    )


def _set_status(db_path: str, run_id: str, status: str) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "UPDATE deployment_runs SET status = %s WHERE id = %s", (status, run_id)
        )
        conn.commit()
    finally:
        conn.close()


def test_keyed_create_proceeds_and_names_its_basis(unconverged_db: str) -> None:
    created = _create(unconverged_db, release_lineage=LINEAGE)

    assert created.replayed is False
    assert created.idempotency_basis == BASIS_UNCONVERGED_REQUEST_MATCH
    assert dr.cmd_get(created.run_id, db_path=unconverged_db) is not None


def test_identical_repeat_returns_the_unstarted_run(unconverged_db: str) -> None:
    first = _create(unconverged_db, release_lineage=LINEAGE)
    again = _create(unconverged_db, release_lineage=LINEAGE)

    assert (again.run_id, again.replayed) == (first.run_id, True)
    assert again.idempotency_basis == BASIS_UNCONVERGED_REQUEST_MATCH
    assert dr.cmd_next_id(db_path=unconverged_db).endswith("-002")


def test_changed_request_is_a_new_run(unconverged_db: str) -> None:
    first = _create(unconverged_db, release_lineage=LINEAGE)
    other = _create(unconverged_db, release_lineage="b" * 40)

    assert other.replayed is False
    assert other.run_id != first.run_id


def test_repeat_after_the_run_started_is_a_new_run(unconverged_db: str) -> None:
    first = _create(unconverged_db, release_lineage=LINEAGE)
    _set_status(unconverged_db, first.run_id, "executing")

    again = _create(unconverged_db, release_lineage=LINEAGE)

    assert again.replayed is False
    assert again.run_id != first.run_id


def test_several_unstarted_matches_refuse_by_name(unconverged_db: str) -> None:
    one = dr.cmd_create_run("yoke", "flow-main", db_path=unconverged_db)
    two = dr.cmd_create_run("yoke", "flow-main", db_path=unconverged_db)

    with pytest.raises(UnconvergedReplayAmbiguous) as refused:
        _create(unconverged_db)

    assert refused.value.code == "idempotency_replay_ambiguous"
    assert refused.value.run_ids == sorted([one, two])
    assert "terminalize RUN-ID --disposition cancelled" in str(refused.value)


def test_early_replay_lookup_defers_to_the_locked_create(
    unconverged_db: str,
) -> None:
    request = canonical_request({"project": "yoke", "flow": "flow-main"})

    assert replay_run("yoke", "release-1", request) is None
