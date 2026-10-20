"""Every deployment-run row lock refuses as ``run_busy`` instead of queueing.

On 2026-10-20 materialize transactions held one run row for up to thirty
minutes and seven requests queued behind it, each from a client that had
already given up. A second request for a held run now refuses within the bound,
naming the holder and its age, and the bound covers only the run row: the
caller's own ``lock_timeout`` is back in force for whatever it locks next.
"""

from __future__ import annotations

import pathlib
import re
import time

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_carried_work import record_carried_work
from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
from yoke_core.domain.deployment_runs_lock import (
    RUN_BUSY_CODE,
    RUN_ROW_LOCK_TIMEOUT_MS,
    DeploymentRunBusy,
    lock_run,
)

pytest_plugins = ["runtime.api.deployment_runs_test_db"]

#: Far below the unbounded wait this replaces, generous for a loaded cluster.
PROMPT_SECONDS = 30.0

_SOURCE_ROOT = (
    pathlib.Path(__file__).resolve().parents[3] / "packages" / "yoke-core" / "src"
)


def _hold_run_row(conn, run_id: str) -> None:
    conn.execute("SELECT status FROM deployment_runs WHERE id=%s FOR UPDATE", (run_id,))


def _terminalize(db_path: str, run_id: str) -> None:
    conn = connect_test_db(db_path)
    try:
        terminalize_run_on(
            conn,
            run_id,
            disposition="cancelled",
            reason="contention test",
            actor_id=None,
            session_id="sess-test",
        )
    finally:
        conn.rollback()
        conn.close()


def _record_carried_work(db_path: str, run_id: str) -> None:
    conn = connect_test_db(db_path)
    try:
        record_carried_work(conn, run_id)
    finally:
        conn.rollback()
        conn.close()


WRITERS = {
    "execution_update": lambda db, run: dr.cmd_update(
        run, "current_stage", "build", db_path=db
    ),
    "terminalize": _terminalize,
    "carried_work": _record_carried_work,
}


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_a_second_request_for_a_held_run_refuses_by_name(
    db_path: str, writer: str
) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    holder = connect_test_db(db_path)
    try:
        _hold_run_row(holder, run_id)

        started = time.monotonic()
        with pytest.raises(DeploymentRunBusy) as raised:
            WRITERS[writer](db_path, run_id)
        elapsed = time.monotonic() - started

        assert RUN_ROW_LOCK_TIMEOUT_MS / 1000 <= elapsed < PROMPT_SECONDS
        text = str(raised.value)
        assert text.startswith(f"{RUN_BUSY_CODE}: deployment run {run_id!r}")
        assert re.search(r"pid \d+ has held a deployment_runs lock for \d+s", text)
        assert "retrying the same command" in text
    finally:
        holder.rollback()
        holder.close()


def test_the_bound_covers_the_run_row_and_nothing_after_it(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        conn.execute("SELECT set_config('lock_timeout', '7s', true)")
        assert lock_run(conn, run_id) == "created"
        assert conn.execute("SELECT current_setting('lock_timeout')").fetchone()[0] == "7s"
    finally:
        conn.rollback()
        conn.close()


def test_no_run_row_lock_bypasses_the_bounded_lock() -> None:
    """A raw ``FOR UPDATE`` on the run row would queue without a bound again.

    Any statement that locks ``deployment_runs`` must follow ``lock_run`` on
    the same run, so the row is already held when it executes.
    """
    offenders = []
    for path in sorted((_SOURCE_ROOT / "yoke_core").rglob("*.py")):
        if path.name == "deployment_runs_lock.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"FOR (NO KEY )?UPDATE", line):
                continue
            window = "\n".join(lines[max(0, index - 8) : index + 1])
            if not re.search(r"\b(?:FROM|JOIN) deployment_runs\b", window):
                continue
            if "lock_run(" not in window:
                offenders.append(f"{path.relative_to(_SOURCE_ROOT)}:{index + 1}")
    assert offenders == []
