"""Run writers read unlocked, re-read unlocked, and bound every lock they take.

A materialize or rematerialize whose run changed after its read used to repeat
the whole run-wide read -- git and HTTP source reads included -- while it held
the run row, and a removal or status update waited on item locks without a
bound. Each now re-reads with the lock released, refuses by name once the run
keeps changing, and refuses a held item lock within the run lock's bound.
"""

from __future__ import annotations

import time

import psycopg
import pytest

from runtime.api.domain import test_deployment_qa_pinned_release_reads as pinned
from runtime.api.domain.test_deployment_qa_materialization_lock_window import (
    STAGE,
    LockWindowRecorder,
    _seed,
)
from yoke_core.domain import db_helpers, deployment_qa_release_version
from yoke_core.domain import deployment_qa_materialization_projection as projection
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item, cmd_update
from yoke_core.domain.deployment_runs_lock import (
    RUN_BUSY_CODE,
    RUN_READ_ATTEMPTS,
    RUN_ROW_LOCK_TIMEOUT_MS,
    DeploymentRunChanging,
)
from yoke_core.domain.qa_plan_rematerialize_deployment import (
    rematerialize_for_deployment_stage,
)

PROMPT_SECONDS = 30.0


def _run_row_locked(run_id: str) -> bool:
    """Whether another backend holds the run row, probed without waiting."""
    probe = db_helpers.connect()
    try:
        probe.execute(
            "SELECT 1 FROM deployment_runs WHERE id=%s FOR UPDATE NOWAIT", (run_id,)
        )
        return False
    except psycopg.errors.LockNotAvailable:
        return True
    finally:
        probe.rollback()
        probe.close()


def _stale_once(monkeypatch) -> list[bool]:
    """The first fingerprint check under the lock answers stale; later ones are real."""
    answers: list[bool] = []
    real = projection.MaterializationProjection.holds

    def holds(self, conn):
        answers.append(bool(answers) and real(self, conn))
        return answers[-1]

    monkeypatch.setattr(projection.MaterializationProjection, "holds", holds)
    return answers


def test_a_stale_read_repeats_its_source_reads_with_the_run_lock_released(
    test_db, monkeypatch
):
    pinned._seed(test_db)
    locked: list[bool] = []
    pinned._count_release_reads(monkeypatch)
    stub_read = deployment_qa_release_version.read_project_file
    stub_fetch = deployment_qa_release_version._fetch

    def read(*args):
        locked.append(_run_row_locked(pinned.RUN))
        return stub_read(*args)

    def fetch(url):
        locked.append(_run_row_locked(pinned.RUN))
        return stub_fetch(url)

    monkeypatch.setattr(deployment_qa_release_version, "read_project_file", read)
    monkeypatch.setattr(deployment_qa_release_version, "_fetch", fetch)
    # Every read reaches the source, so a re-read cannot hide behind a cache.
    monkeypatch.setattr(
        deployment_qa_release_version, "shared_read", lambda _c, _k, reader: reader()
    )
    answers = _stale_once(monkeypatch)

    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=pinned.RUN,
        deployment_stage=pinned.ITEM_QA_STAGE,
        deployment_member_item_id=pinned.MEMBERS[0],
    )

    assert answers[:2] == [False, True]
    assert len(locked) >= 4  # the pin file and the release record, read twice
    assert not any(locked), locked


def test_a_run_changed_between_read_and_lock_is_read_again_unlocked(
    test_db, monkeypatch
):
    from yoke_core.domain.deployment_run_member_removal import remove_members_on

    run_id = "run-unlocked-reread-moved"
    first, peer = _seed(test_db, run_id, 21001, 2, requirements=1)
    reads: list[tuple[int, bool]] = []
    real = projection.MaterializationProjection.shareable

    def shareable(self, subject, target, snapshots):
        answer = real(self, subject, target, snapshots)
        reads.append((len(answer), _run_row_locked(run_id)))
        if len(reads) == 1:
            remove_members_on(test_db, run_id, [peer], reason="moved mid-read")
            test_db.commit()
        return answer

    monkeypatch.setattr(projection.MaterializationProjection, "shareable", shareable)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=first,
    )
    # Shared on the stale read, private once re-read, and never under the lock.
    assert reads == [(2, False), (0, False)]


@pytest.mark.parametrize("writer", ["materialize", "rematerialize"])
def test_a_run_that_keeps_changing_refuses_by_name(test_db, monkeypatch, writer):
    run_id = f"run-unlocked-reread-churn-{writer}"
    (member,) = _seed(test_db, run_id, 22001 if writer == "materialize" else 22101, 1)
    if writer == "rematerialize":
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )
    before = test_db.execute(
        "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s", (run_id,)
    ).fetchone()[0]
    checks: list[int] = []
    monkeypatch.setattr(
        projection.MaterializationProjection,
        "holds",
        lambda self, conn: checks.append(1) and False,
    )
    write = (
        materialize_deployment_qa_stage
        if writer == "materialize"
        else rematerialize_for_deployment_stage
    )

    with pytest.raises(DeploymentRunChanging) as raised:
        write(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=STAGE,
            deployment_member_item_id=member,
        )

    assert len(checks) == RUN_READ_ATTEMPTS
    text = str(raised.value)
    assert text.startswith(f"{RUN_BUSY_CODE}: deployment run {run_id!r}")
    assert "(run_read_changed)" in text
    assert f"yoke watch deploy -- {run_id}" in text
    test_db.rollback()
    assert not _run_row_locked(run_id)
    after = test_db.execute(
        "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s", (run_id,)
    ).fetchone()[0]
    assert after == before


def _hold_item(run_id: str, item_id: int):
    holder = db_helpers.connect()
    holder.execute("SELECT id FROM items WHERE id=%s FOR UPDATE", (item_id,))
    return holder


def _assert_prompt_lock_refusal(started: float, text: str, run_id: str) -> None:
    elapsed = time.monotonic() - started
    assert RUN_ROW_LOCK_TIMEOUT_MS / 1000 <= elapsed < PROMPT_SECONDS
    assert text.startswith("deployment_start_lock_busy:"), text
    assert f"yoke deployment-runs get {run_id}" in text


def test_removal_refuses_a_held_member_lock_within_the_bound(test_db):
    run_id = "run-unlocked-reread-remove"
    members = _seed(test_db, run_id, 23001, 2, requirements=1)
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (members[0],))
    test_db.commit()
    holder = _hold_item(run_id, members[0])
    try:
        started = time.monotonic()
        with pytest.raises(ValueError) as raised:
            cmd_remove_item(run_id, members[0], reason="split out of the release")
        _assert_prompt_lock_refusal(started, str(raised.value), run_id)
    finally:
        holder.rollback()
        holder.close()
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (run_id, members[0]),
    ).fetchone()


def test_status_update_refuses_a_held_member_lock_within_the_bound(test_db):
    run_id = "run-unlocked-reread-update"
    members = _seed(test_db, run_id, 24001, 2, requirements=1)
    holder = _hold_item(run_id, members[1])
    try:
        started = time.monotonic()
        refusal = cmd_update(run_id, "status", "failed")
        assert refusal is not None
        _assert_prompt_lock_refusal(
            started, refusal.removeprefix("Error: "), run_id
        )
    finally:
        holder.rollback()
        holder.close()
    status = test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    assert status == "executing"


def test_materialize_and_refresh_every_member_grow_at_most_linearly(test_db):
    """Forty members cost at most four times ten, so O(n^2) work fails here.

    A shared group's refresh reads its owners as one set and rewrites only
    owners whose selection changed, so refreshing every member in turn is
    linear in members, inside the run lock and out.
    """
    measured = {}
    for run_id, first, size in (
        ("run-unlocked-reread-ten", 25001, 10),
        ("run-unlocked-reread-forty", 26001, 40),
    ):
        members = _seed(test_db, run_id, first, size, requirements=1)
        materialized, refreshed = LockWindowRecorder(test_db), LockWindowRecorder(test_db)
        for member in members:
            materialize_deployment_qa_stage(
                materialized,
                deployment_run_id=run_id,
                deployment_stage=STAGE,
                deployment_member_item_id=member,
            )
        for member in members:
            rematerialize_for_deployment_stage(
                refreshed,
                deployment_run_id=run_id,
                deployment_stage=STAGE,
                deployment_member_item_id=member,
            )
        measured[size] = (*materialized.counts(), *refreshed.counts())
    ten, forty = measured[10], measured[40]
    assert all(large <= 4 * small for small, large in zip(ten, forty)), measured
