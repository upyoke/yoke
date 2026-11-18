"""Scheduled universe pruning: upkeep runs retention and keeps a receipt.

Control-plane upkeep (:mod:`yoke_core.domain.control_plane_upkeep`) calls
:func:`run_scheduled_prune` on every cycle. It runs the same stateless pass
loop as ``yoke universe prune --apply``, under the universe's effective
retention policy, and writes one ``universe_prune_receipts`` row per run:
rows deleted per table, elapsed time, outcome, and any refusal.

A run is due when no receipt exists, when the last run's budget ended with
rows still eligible (a backlog keeps draining on each cycle), or when the
last run started :data:`CADENCE` ago. Each run stops after
:data:`RUN_BUDGET_SECONDS`, so upkeep's host keeps its own cadence. One
process at a time runs it: on PostgreSQL a session advisory lock guards the
due check and the run.

A run that drains on PostgreSQL then runs plain ``VACUUM`` on every table
deleted from since the previous drain, so the freed space is reused instead
of growing the files. Nothing shrinks the files; that is not the goal.
SQLite has no plain vacuum, so it relies on its own free-page reuse.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_contracts.universe_prune_tally import PruneTally
from yoke_contracts.universe_retention import PruneRequest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.universe_prune_receipt_schema import (
    OUTCOME_BUDGET,
    OUTCOME_DRAINED,
    OUTCOME_FAILED,
    UNIVERSE_PRUNE_RECEIPTS_TABLE,
)


_LOG = logging.getLogger(__name__)

CADENCE = timedelta(hours=6)
RUN_BUDGET_SECONDS = 60.0
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"universe-scheduled-prune").digest()[:8], "big", signed=True
)
FAILED_RECOVERY = (
    "Fix the condition the reason names. Upkeep retries at its next scheduled "
    "run (every 6 hours); an organization administrator can run "
    "`yoke universe prune --apply` now."
)


@dataclass(frozen=True)
class PruneReceipt:
    id: int
    started_at: datetime
    completed_at: datetime
    elapsed_ms: int
    outcome: str
    deleted: dict[str, int]
    unfinished: list[dict[str, Any]]
    vacuumed: list[str]
    failure_code: str
    failure_reason: str
    failure_recovery: str


_COLUMNS = (
    "id, started_at, completed_at, elapsed_ms, outcome, deleted, unfinished, "
    "vacuumed, failure_code, failure_reason, failure_recovery"
)


def _mark(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _receipt(row: Any) -> PruneReceipt:
    return PruneReceipt(
        id=int(row[0]),
        started_at=parse_instant(row[1]),
        completed_at=parse_instant(row[2]),
        elapsed_ms=int(row[3]),
        outcome=str(row[4]),
        deleted=json.loads(row[5] or "{}"),
        unfinished=json.loads(row[6] or "[]"),
        vacuumed=json.loads(row[7] or "[]"),
        failure_code=str(row[8] or ""),
        failure_reason=str(row[9] or ""),
        failure_recovery=str(row[10] or ""),
    )


def latest_receipt(conn: Any, *, outcomes: tuple[str, ...] = ()) -> PruneReceipt | None:
    """The newest receipt, optionally among ``outcomes``; None before any."""
    if not _table_exists(conn, UNIVERSE_PRUNE_RECEIPTS_TABLE):
        return None
    p = _mark(conn)
    where = (
        f" WHERE outcome IN ({','.join(p for _ in outcomes)})" if outcomes else ""
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM universe_prune_receipts{where} "
        "ORDER BY started_at DESC, id DESC LIMIT 1",
        tuple(outcomes),
    ).fetchone()
    return None if row is None else _receipt(row)


def prune_due(latest: PruneReceipt | None, now: datetime) -> bool:
    if latest is None or latest.outcome == OUTCOME_BUDGET:
        return True
    return latest.started_at <= now - CADENCE


@contextmanager
def _single_runner(conn: Any) -> Iterator[bool]:
    if not db_backend.connection_is_postgres(conn):
        yield True
        return
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
    conn.commit()
    if not (row and row[0]):
        yield False
        return
    try:
        yield True
    finally:
        try:
            conn.rollback()
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            conn.commit()
        except Exception:  # noqa: BLE001 - closing the session releases it
            _LOG.warning("scheduled prune lock release failed", exc_info=True)


def _refusal(exc: Exception) -> dict[str, str]:
    text = str(exc).strip() or type(exc).__name__
    code, sep, _ = text.partition(":")
    if not sep or not code.isidentifier():
        code = "retention_scheduled_prune_failed"
    return {"code": code, "reason": text, "recovery": FAILED_RECOVERY}


def _drain(conn: Any, tally: PruneTally, budget: float, clock: Callable[[], float]):
    """Run passes until nothing is left or the budget ends.

    ``tally`` keeps every acknowledged pass, so a later pass that raises
    still leaves the earlier committed counts on the receipt.
    """
    from yoke_core.domain.universe_retention_pass import prune_pass

    started = clock()
    request = PruneRequest(apply=True)
    while True:
        result = prune_pass(conn, request)
        tally.record(result)
        if result.get("failure"):
            return OUTCOME_FAILED, result, result["failure"]
        if result["cycle_complete"] and not tally.next_cycle():
            return OUTCOME_DRAINED, result, None
        if clock() - started >= budget:
            return OUTCOME_BUDGET, result, None
        request = PruneRequest(
            apply=True,
            cutoff=result["cutoff"],
            expected_digest=result["policy_digest"],
            table_index=result["next_table_index"],
            skip_tables=tally.skip_tables,
        )


def _tables_since_drain(conn: Any, deleted: dict[str, int]) -> list[str]:
    """Tables with deletions since the previous drained run, this run included."""
    previous = latest_receipt(conn, outcomes=(OUTCOME_DRAINED,))
    sql = "SELECT deleted FROM universe_prune_receipts"
    params: tuple[Any, ...] = ()
    if previous is not None:
        sql += f" WHERE started_at > {_mark(conn)}"
        params = (instant_parameter(conn, previous.started_at),)
    rows = conn.execute(sql, params).fetchall()
    conn.commit()
    tables = {t for t, n in deleted.items() if n}
    for row in rows:
        tables |= {t for t, n in json.loads(row[0] or "{}").items() if n}
    return sorted(tables)


def _vacuum(conn: Any, tables: list[str]) -> list[str]:
    """Plain VACUUM so deleted rows' space is reused; never VACUUM FULL."""
    if not tables or not db_backend.connection_is_postgres(conn):
        return []
    conn.commit()
    prior = conn.autocommit
    conn.autocommit = True
    done = []
    try:
        for table in tables:
            try:
                conn.execute(f'VACUUM "{table}"')
                done.append(table)
            except Exception:  # noqa: BLE001 - autovacuum still owns it
                _LOG.warning("scheduled prune VACUUM %s failed", table, exc_info=True)
    finally:
        conn.autocommit = prior
    return done


def run_scheduled_prune(
    conn: Any,
    *,
    now: datetime | None = None,
    budget: float = RUN_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one due prune and write its receipt; report why when not due."""
    with _single_runner(conn) as held:
        if not held:
            return {"ran": False, "reason": "another process is running it"}
        current = utc_now() if now is None else now
        if not prune_due(latest_receipt(conn), current):
            conn.commit()
            return {"ran": False, "reason": "not due"}
        conn.commit()
        started = clock()
        result: dict[str, Any] = {}
        tally = PruneTally(apply=True)
        try:
            outcome, result, failure = _drain(conn, tally, budget, clock)
        except Exception as exc:  # noqa: BLE001 - the receipt names it
            conn.rollback()
            outcome, failure = OUTCOME_FAILED, _refusal(exc)
        deleted = {t: n for t, n in tally.deleted.items() if n}
        vacuumed = (
            _vacuum(conn, _tables_since_drain(conn, deleted))
            if outcome == OUTCOME_DRAINED
            else []
        )
        receipt = {
            "started_at": current,
            "completed_at": utc_now(),
            "elapsed_ms": int((clock() - started) * 1000),
            "outcome": outcome,
            "cutoff": parse_instant(result["cutoff"]) if result.get("cutoff") else None,
            "policy_digest": str(result.get("policy_digest") or ""),
            "deleted": json.dumps(deleted, sort_keys=True),
            "unfinished": json.dumps(list(tally.unfinished.values()), sort_keys=True),
            "vacuumed": json.dumps(vacuumed),
            "failure_code": (failure or {}).get("code", ""),
            "failure_reason": (failure or {}).get("reason", ""),
            "failure_recovery": (failure or {}).get("recovery", ""),
        }
        _write_receipt(conn, receipt)
        if failure:
            _LOG.warning(
                "scheduled prune failed: %s: %s", receipt["failure_code"], receipt["failure_reason"]
            )
        return {"ran": True, **receipt, "started_at": format_instant(current)}


def _write_receipt(conn: Any, receipt: dict[str, Any]) -> None:
    p = _mark(conn)
    columns = list(receipt)
    values = tuple(
        instant_parameter(conn, v) if isinstance(v, datetime) else v
        for v in receipt.values()
    )
    conn.execute(
        f"INSERT INTO universe_prune_receipts ({', '.join(columns)}) "
        f"VALUES ({', '.join(p for _ in columns)})",
        values,
    )
    conn.commit()


__all__ = [
    "CADENCE",
    "PruneReceipt",
    "RUN_BUDGET_SECONDS",
    "latest_receipt",
    "prune_due",
    "run_scheduled_prune",
]
