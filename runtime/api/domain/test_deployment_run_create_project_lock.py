"""Run creation serializes per project, and run ids stay unique across them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    two_project_release,
)
from yoke_core.domain.db_helpers import connect, utc_now
from yoke_core.domain.deployment_run_create_write import create_run
from yoke_core.domain.deployment_run_id_allocation import reserve_run_id
from yoke_core.domain.project_identity import resolve_project_id

_HOLD_CREATE_LOCK = (
    "SELECT pg_advisory_xact_lock(hashtext('deployment_runs.create'), %s::int)"
)


def _release(test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s", (CARRIER_FLOW,)
    )
    test_db.execute("DELETE FROM deployment_runs WHERE id='run-candidate'")
    test_db.commit()
    from runtime.api.fixtures.carried_release_candidate import git

    return git(release["carrier_repo"], "rev-parse", "HEAD").strip()


def test_another_projects_create_does_not_wait_on_this_one(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lineage = _release(test_db, tmp_path, monkeypatch)
    holder = connect()
    try:
        other = resolve_project_id(test_db, "yoke") + 1000
        holder.execute(_HOLD_CREATE_LOCK, (other,))

        created = create_run("yoke", CARRIER_FLOW, release_lineage=lineage)

        assert created.replayed is False
    finally:
        holder.rollback()
        holder.close()


def test_a_create_waits_on_its_own_project(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lineage = _release(test_db, tmp_path, monkeypatch)
    holder = connect()
    try:
        holder.execute(_HOLD_CREATE_LOCK, (resolve_project_id(test_db, "yoke"),))

        with pytest.raises(ValueError, match="deployment_start_lock_busy"):
            create_run("yoke", CARRIER_FLOW, release_lineage=lineage)
    finally:
        holder.rollback()
        holder.close()


def test_concurrent_creates_reserve_distinct_run_ids(test_db: Any) -> None:
    first, second = connect(), connect()
    try:
        now = utc_now()
        held = reserve_run_id(first, now)
        # The first id is held uncommitted, so the next creation skips it.
        assert reserve_run_id(second, now) != held
        second.rollback()
        first.rollback()
        # Released without a row, the id is free again.
        assert reserve_run_id(second, now) == held
    finally:
        first.close()
        second.close()
