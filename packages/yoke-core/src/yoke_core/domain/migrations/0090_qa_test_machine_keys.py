"""Name a QA host a test machine in every QA-owned stored key.

``machine`` and ``machine_id`` now mean only a registered Yoke Machine (the
``machines`` table). QA's own stored surfaces converge here so no reader has
to recognize the retired spelling:

- The Test Machine waiting line moves from ``qa_host_waits`` (keyed by
  ``machine_id``) to ``qa_test_machine_waits`` (keyed by ``test_machine``).
  Every row is copied under its own id and the old table is dropped, so
  this entry retires the ``0075_qa_host_wait_line`` invariant that the old
  table exists. A new table, not a column rename, because the applied
  ``0075`` body still creates and fills the old shape when full history
  replays against a current schema.
- ``qa_plan_executions.machine_lease_id`` becomes ``test_machine_lease_id``.
- A ``qa_admission`` work claim's scope ``{"machine_id": NAME}`` becomes
  ``{"test_machine": NAME}``.
- ``method_config`` keys ``machine`` / ``machines`` become ``test_machine`` /
  ``test_machines`` in plan cases, materialized requirements, each run's
  start-bound config snapshot and each execution's frozen roster.
- Host-control evidence and QA artifact metadata name their host
  ``test_machine``. Recorded run evidence is immutable, so only this
  entry's own key fold may rewrite it (see ``_fold_run_results``).

Digest consistency: a pass stays current only while its run's recorded
``method_config`` snapshot equals the requirement's, so both sides fold the
same way and keep their in-place correction marker. A frozen roster is
verified against ``roster_digest``, so a folded roster stores the digest the
roster reader computes. Plan-case refresh digests are derived on read from
both sides and need no stored value. Review bundles are left as captured:
their digest is the identity a reviewer submits and no reader takes a host
key from them.
"""

from __future__ import annotations

from typing import Any, Callable

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.migrations._qa_test_machine_documents import (
    compact,
    fold_artifact_metadata,
    fold_method_config,
    fold_roster,
    fold_run_result,
    parsed,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.schema_migrations import (
    QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_NAME as RUN_EVIDENCE_TRIGGER,
    QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL,
)

#: Older builds read and write the retired keys.
MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0075_qa_host_wait_line",)
RETIRED_WAIT_TABLE = "qa_host_waits"
WAIT_TABLE = "qa_test_machine_waits"
RETIRED_SCOPE_KEY = "machine_id"
CURRENT_SCOPE_KEY = "test_machine"
QA_ADMISSION = "qa_admission"
EXECUTION_TABLE = "qa_plan_executions"
RETIRED_LEASE_COLUMN = "machine_lease_id"
CURRENT_LEASE_COLUMN = "test_machine_lease_id"
#: Written here rather than imported from the schema module, because a
#: history entry has to load from whatever build applies it.
WAIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS qa_test_machine_waits (
    id TEXT PRIMARY KEY,
    test_machine TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL,
    qa_plan_execution_id TEXT REFERENCES qa_plan_executions(id),
    state TEXT NOT NULL CHECK(state IN ('waiting','reserved','granted','cancelled')),
    claim_id INTEGER REFERENCES work_claims(id),
    resume_command TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    settled_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_test_machine_waits_live_session
    ON qa_test_machine_waits(test_machine, session_id)
    WHERE state IN ('waiting','reserved');
CREATE INDEX IF NOT EXISTS idx_qa_test_machine_waits_line
    ON qa_test_machine_waits(test_machine, state, queued_at);
"""
#: Every column after the host key, shared by the retired and current line.
_WAIT_COLUMNS = (
    "session_id", "actor_id", "queued_at", "qa_plan_execution_id", "state",
    "claim_id", "resume_command", "rationale", "settled_at",
)
#: Each stored document: table, key column, JSON column, row filter, fold.
_DOCUMENTS: tuple[tuple[str, str, str, str, Callable[[Any], Any]], ...] = (
    ("qa_plan_cases", "id", "method_config", "%\"machine%", fold_method_config),
    ("qa_requirements", "id", "method_config", "%\"machine%", fold_method_config),
    ("qa_artifacts", "id", "metadata", "%\"machine\"%", fold_artifact_metadata),
)


def _marker(conn: Any) -> str:
    return "%s" if connection_is_postgres(conn) else "?"


def _rename_column(conn: Any, table: str, retired: str, current: str) -> None:
    """Keep every stored value while converging either pre-boot shape.

    A boot that already added ``current`` leaves both columns: values move
    into ``current`` where it is still empty, then ``retired`` is dropped.
    """
    if not _table_exists(conn, table) or not _column_exists(conn, table, retired):
        return
    if _column_exists(conn, table, current):
        conn.execute(
            f'UPDATE "{table}" SET "{current}" = "{retired}" '
            f'WHERE "{current}" IS NULL'
        )
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{retired}"')
    else:
        conn.execute(
            f'ALTER TABLE "{table}" RENAME COLUMN "{retired}" TO "{current}"'
        )


def _move_wait_line(conn: Any) -> None:
    """Copy each retired-line row into the current line, then drop the old one.

    A row whose id is already present was copied before; a live row is
    skipped when the current line already holds that session's live wait on
    the same test machine, which keeps the one-live-wait index satisfied.
    """
    if not _table_exists(conn, RETIRED_WAIT_TABLE):
        return
    execute_schema_script(conn, WAIT_TABLE_SQL)
    machine = (
        "machine_id"
        if _column_exists(conn, RETIRED_WAIT_TABLE, "machine_id")
        else "test_machine"
    )
    columns = ",".join(_WAIT_COLUMNS)
    selected = ",".join(f"o.{column}" for column in _WAIT_COLUMNS)
    conn.execute(
        f"INSERT INTO {WAIT_TABLE}(id,test_machine,{columns}) "
        f"SELECT o.id,o.{machine},{selected} FROM {RETIRED_WAIT_TABLE} o "
        f"WHERE NOT EXISTS (SELECT 1 FROM {WAIT_TABLE} n WHERE n.id=o.id) "
        "AND NOT (o.state IN ('waiting','reserved') AND EXISTS ("
        f"SELECT 1 FROM {WAIT_TABLE} n WHERE n.test_machine=o.{machine} "
        "AND n.session_id=o.session_id AND n.state IN ('waiting','reserved')))"
    )
    conn.execute(f"DROP TABLE IF EXISTS {RETIRED_WAIT_TABLE}")


def _rename_claim_scopes(conn: Any) -> None:
    """Re-key each host lease scope in the claim table's canonical encoding."""
    if not _table_exists(conn, "work_claims"):
        return
    p = _marker(conn)
    rows = conn.execute(
        "SELECT id, scope, released_at FROM work_claims "
        f"WHERE target_kind={p} AND scope LIKE {p} ORDER BY id",
        (QA_ADMISSION, f'%"{RETIRED_SCOPE_KEY}"%'),
    ).fetchall()
    for claim_id, raw, released_at in rows:
        scope = parsed(raw)
        if not isinstance(scope, dict) or RETIRED_SCOPE_KEY not in scope:
            continue
        value = scope.pop(RETIRED_SCOPE_KEY)
        scope.setdefault(CURRENT_SCOPE_KEY, value)
        encoded = compact(scope)
        if released_at is None and conn.execute(
            "SELECT 1 FROM work_claims WHERE target_kind=" + p + " AND scope=" + p
            + " AND released_at IS NULL AND id<>" + p,
            (QA_ADMISSION, encoded, claim_id),
        ).fetchone():
            raise RuntimeError(
                f"qa_admission_scope_conflict: live claim {claim_id} and another "
                f"live claim both hold test machine {value!r}. Recovery: release "
                "the stale one with yoke claims work release --claim-id ID, then "
                "retry rehearsal or boot."
            )
        conn.execute(
            f"UPDATE work_claims SET scope={p} WHERE id={p}", (encoded, claim_id)
        )


def _folded_rows(
    conn: Any, table: str, key: str, column: str, pattern: str, fold: Any
) -> list[tuple[str, Any]]:
    """Each row whose stored document the fold changes, re-encoded compactly."""
    if not _column_exists(conn, table, column):
        return []
    rows = conn.execute(
        f"SELECT {key}, {column} FROM {table} WHERE {column} LIKE {_marker(conn)} "
        f"ORDER BY {key}",
        (pattern,),
    ).fetchall()
    changed = []
    for row_key, raw in rows:
        document = parsed(raw)
        folded = fold(document)
        if folded != document:
            changed.append((compact(folded), row_key))
    return changed


def _write(conn: Any, table: str, key: str, column: str, rows: list) -> None:
    p = _marker(conn)
    for encoded, row_key in rows:
        conn.execute(
            f"UPDATE {table} SET {column}={p} WHERE {key}={p}", (encoded, row_key)
        )


def _fold_documents(conn: Any) -> None:
    for table, key, column, pattern, fold in _DOCUMENTS:
        _write(conn, table, key, column, _folded_rows(
            conn, table, key, column, pattern, fold
        ))


def _fold_run_results(conn: Any) -> None:
    """Re-key recorded runs inside this entry's transaction only.

    ``raw_result`` is immutable once a verdict is set. The fold renames keys
    without changing any value, so the immutability trigger is suspended for
    exactly these updates and restored in the same transaction: a failed
    apply rolls the suspension back with the rows.
    """
    rows = _folded_rows(
        conn, "qa_runs", "id", "raw_result", '%"machine%', fold_run_result
    )
    if not rows:
        return
    if connection_is_postgres(conn):
        state = conn.execute(
            "SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c "
            "ON c.oid=t.tgrelid WHERE c.relname='qa_runs' "
            "AND c.relnamespace=current_schema()::regnamespace "
            "AND t.tgname=%s AND NOT t.tgisinternal",
            (RUN_EVIDENCE_TRIGGER,),
        ).fetchone()
        suspend = state is not None and str(state[0]) != "D"
        if suspend:
            conn.execute(f"ALTER TABLE qa_runs DISABLE TRIGGER {RUN_EVIDENCE_TRIGGER}")
        _write(conn, "qa_runs", "id", "raw_result", rows)
        if suspend:
            conn.execute(f"ALTER TABLE qa_runs ENABLE TRIGGER {RUN_EVIDENCE_TRIGGER}")
        return
    existed = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
        (RUN_EVIDENCE_TRIGGER,),
    ).fetchone()
    conn.execute(f"DROP TRIGGER IF EXISTS {RUN_EVIDENCE_TRIGGER}")
    _write(conn, "qa_runs", "id", "raw_result", rows)
    if existed:
        conn.execute(QA_RUNS_VERDICT_IMMUTABLE_TRIGGER_SQL)


def _fold_rosters(conn: Any) -> None:
    """Fold each frozen roster and store the digest its reader verifies."""
    from yoke_core.domain.qa_plan_execution_store import roster_digest

    if not _column_exists(conn, "qa_plan_executions", "roster_json"):
        return
    p = _marker(conn)
    rows = conn.execute(
        "SELECT id, roster_json FROM qa_plan_executions "
        f"WHERE roster_json LIKE {p} ORDER BY id",
        ('%"machine%',),
    ).fetchall()
    for execution_id, raw in rows:
        roster = parsed(raw)
        folded = fold_roster(roster)
        if folded == roster:
            continue
        conn.execute(
            "UPDATE qa_plan_executions SET roster_json=" + p + ", roster_digest="
            + p + " WHERE id=" + p,
            (compact(folded), roster_digest(folded), execution_id),
        )


def apply(conn: Any) -> None:
    _move_wait_line(conn)
    _rename_column(
        conn, EXECUTION_TABLE, RETIRED_LEASE_COLUMN, CURRENT_LEASE_COLUMN
    )
    _rename_claim_scopes(conn)
    _fold_documents(conn)
    _fold_run_results(conn)
    _fold_rosters(conn)


def invariants(conn: Any) -> None:
    """Prove the waiting line and lease name their host only as a test machine."""
    assert not _table_exists(conn, RETIRED_WAIT_TABLE), (
        f"{RETIRED_WAIT_TABLE} remains after the test machine rename; rerun "
        "this entry's rehearsal"
    )
    if _table_exists(conn, WAIT_TABLE):
        assert _column_exists(conn, WAIT_TABLE, "test_machine"), (
            f"{WAIT_TABLE}.test_machine is missing after the test machine rename"
        )
    if _table_exists(conn, EXECUTION_TABLE):
        assert _column_exists(conn, EXECUTION_TABLE, CURRENT_LEASE_COLUMN), (
            f"{EXECUTION_TABLE}.{CURRENT_LEASE_COLUMN} is missing after the "
            "test machine rename"
        )
        assert not _column_exists(conn, EXECUTION_TABLE, RETIRED_LEASE_COLUMN), (
            f"{EXECUTION_TABLE}.{RETIRED_LEASE_COLUMN} remains after the test "
            "machine rename"
        )


__all__ = [
    "CURRENT_LEASE_COLUMN",
    "EXECUTION_TABLE",
    "MINIMUM_SERVING_VERSION",
    "RETIRED_LEASE_COLUMN",
    "RETIRED_WAIT_TABLE",
    "RETIRES_INVARIANTS",
    "WAIT_TABLE",
    "apply",
    "invariants",
]
