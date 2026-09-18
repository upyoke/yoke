# ruff: noqa: F811
"""A run's own success write outlives whatever its notices do.

The release-wait close-out notice rides the run-completion path, and it
originally rode INSIDE the transaction carrying ``status='succeeded'``. On
Postgres any failed statement aborts that transaction, so one undeliverable
notice would have rolled back the delivery it was announcing — the worst
possible trade, since the deploy really happened.

So the notice is sent strictly after the status commit. These prove the
ordering by the only thing that distinguishes it: a notice that blows up
cannot take the status with it.
"""

from __future__ import annotations

from yoke_core.domain import deployment_runs as dr
from runtime.api.test_deployment_runs_full_helpers import (  # noqa: F401
    _conn,
    _placeholder,
    db_path,
)


def _raise(*_args, **_kwargs):
    raise RuntimeError("notice transport is down")


def test_a_raising_notice_does_not_roll_back_succeeded(db_path, monkeypatch):
    rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    dr.cmd_update(rid, "status", "executing", db_path=db_path)
    monkeypatch.setattr(
        "yoke_core.domain.deployment_delivery_close_out_notice."
        "notify_delivery_cleared",
        _raise,
    )

    try:
        dr.cmd_update(rid, "status", "succeeded", db_path=db_path)
    except RuntimeError:
        pass

    assert dr.cmd_get(rid, field="status", db_path=db_path) == "succeeded"
    conn = _conn(db_path)
    p = _placeholder(conn)
    completed = conn.execute(
        f"SELECT completed_at FROM deployment_runs WHERE id={p}", (rid,)
    ).fetchone()[0]
    conn.close()
    assert completed is not None


def test_the_notice_is_sent_after_the_status_commit(db_path, monkeypatch):
    """Ordering, proved from a SECOND connection.

    Reading the run on the caller's own connection would show 'succeeded'
    either way — that connection is inside the transaction doing the write.
    Only a separate connection distinguishes committed from pending, which
    is the whole distinction this ordering exists for.
    """
    rid = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    dr.cmd_update(rid, "status", "executing", db_path=db_path)
    observed: list = []

    def observe(_conn_in_transaction, *, run_id, **_kwargs):
        other = _conn(db_path)
        p = _placeholder(other)
        row = other.execute(
            f"SELECT status FROM deployment_runs WHERE id={p}", (run_id,)
        ).fetchone()
        other.close()
        observed.append(row["status"] if hasattr(row, "keys") else row[0])
        return []

    monkeypatch.setattr(
        "yoke_core.domain.deployment_delivery_close_out_notice."
        "notify_delivery_cleared",
        observe,
    )

    assert dr.cmd_update(rid, "status", "succeeded", db_path=db_path) is None
    assert observed == ["succeeded"]
