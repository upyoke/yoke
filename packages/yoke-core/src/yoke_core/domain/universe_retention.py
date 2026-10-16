"""Existing-schema settings and bounded, output-only universe pruning."""

from __future__ import annotations

from datetime import datetime
from contextlib import ExitStack
import json
import time

from yoke_contracts.retention_defaults import RETENTION_KEY
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_contracts.universe_retention import RetentionPolicy
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.schema_common import _table_exists


def read_policy(conn):
    """Reads never seed or overwrite; absent storage uses shipped defaults."""
    if not _table_exists(conn, "universe_settings"):
        return RetentionPolicy(), "default"
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT value FROM universe_settings WHERE key={p}", (RETENTION_KEY,)
    ).fetchone()
    if row is None:
        return RetentionPolicy(), "default"
    try:
        return RetentionPolicy.model_validate(json.loads(row[0])), "universe"
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "retention_policy_invalid: stored retention settings do not match supported version 1. "
            "Recovery: ask the universe administrator to restore a valid retention document; "
            "no policy editor ships with this command."
        ) from exc


def seed_defaults(conn):
    """Normal initialization only; the caller owns the seed transaction."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO universe_settings (key,value,updated_at) "
        f"VALUES ({p},{p},{p}) ON CONFLICT(key) DO NOTHING",
        (
            RETENTION_KEY,
            RetentionPolicy().model_dump_json(),
            instant_parameter(conn, utc_now()),
        ),
    )


def read_retention(conn, cutoff=None):
    policy, source = read_policy(conn)
    cards = conn.execute(
        "SELECT id,slug,name FROM organizations ORDER BY id LIMIT 2"
    ).fetchall()
    if len(cards) != 1:
        raise ValueError(
            "retention_universe_identity_unavailable: expected one organization identity. "
            "Recovery: ask the universe administrator to repair the identity before pruning."
        )
    return policy, {
        "universe": dict(zip(("org_id", "slug", "name"), cards[0])),
        "source": source,
        "policy": policy.model_dump(),
        "policy_digest": policy.digest,
        "cutoff": format_instant(cutoff or utc_now()),
    }


def _execute(conn, policy, deadline, sql, params=()):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("retention_pass_budget")
    if db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT set_config('statement_timeout',%s,true)",
            (f"{max(1, int(min(policy.statement_seconds, remaining) * 1000))}ms",),
        )
        conn.execute(
            "SELECT set_config('lock_timeout',%s,true)",
            (f"{max(1, int(min(policy.lock_seconds, remaining) * 1000))}ms",),
        )
    else:
        sql = sql.replace("%s", "?")
    values = tuple(
        instant_parameter(conn, v) if isinstance(v, datetime) else v for v in params
    )
    return conn.execute(sql, values)


def _hold_policy(conn, policy, deadline):
    """Share-lock the settings row so the policy cannot change mid-cohort."""
    lock = " FOR SHARE" if db_backend.connection_is_postgres(conn) else ""
    row = _execute(
        conn,
        policy,
        deadline,
        "SELECT value FROM universe_settings WHERE key=%s" + lock,
        (RETENTION_KEY,),
    ).fetchone()
    current = RetentionPolicy.model_validate(json.loads(row[0])) if row else None
    if (current or RetentionPolicy()).digest != policy.digest:
        raise ValueError(
            "retention_policy_changed: recovery: review settings and rerun universe prune."
        )


def _hold_cohort(conn, policy, deadline, rule):
    """Lock only what this cohort needs; never whole message tables.

    Row locks taken by the eligibility select and the settings-row share lock
    replace table-wide custody, so prune never queues behind (or ahead of) the
    message writers' row order. Snapshot inventories keep one table lock:
    native readers take it, and no message writer touches these tables.
    """
    _hold_policy(conn, policy, deadline)
    if rule.table == "path_snapshots" and db_backend.connection_is_postgres(conn):
        _execute(
            conn,
            policy,
            deadline,
            "LOCK TABLE path_snapshots,path_snapshot_entries,path_snapshot_symlink_facts IN ACCESS EXCLUSIVE MODE",
        )


def _key_where(keys, rows):
    columns = "(" + ",".join(keys) + ")"
    marks = "(" + ",".join("%s" for _ in keys) + ")"
    clause = columns + " IN (" + ",".join(marks for _ in rows) + ")"
    return clause, tuple(value for row in rows for value in row)


def _delete_cohort(conn, policy, deadline, rule, rows, custody):
    from yoke_core.domain.retention_operational_policy import upload_lock

    deleted, protected = {}, 0
    remaining = policy.batch_rows
    if (
        rule.table == "function_call_ledger"
        and rows
        and db_backend.connection_is_postgres(conn)
    ):
        from yoke_core.domain.yoke_function_dispatch_idempotency import _reservation_key

        marks = ",".join("(%s,%s)" for _ in rows)
        params = tuple(
            value for row in rows for value in (row[0], _reservation_key(row[0]))
        )
        admitted = _execute(
            conn,
            policy,
            deadline,
            f"SELECT request_id FROM (VALUES {marks}) AS candidates(request_id,lock_key) WHERE pg_try_advisory_xact_lock(lock_key::bigint)",
            params,
        ).fetchall()
        protected += len(rows) - len(admitted)
        rows = admitted
    # Snapshot cohorts contain one whole inventory, regardless of child count.
    # Other parent/child graphs must fit the physical row cap atomically.
    accepted = []
    child_counts = {}
    for table, child_key, parent_key in rule.children:
        values = tuple(row[rule.keys.index(parent_key)] for row in rows)
        if values:
            marks = ",".join("%s" for _ in values)
            found = _execute(
                conn,
                policy,
                deadline,
                f"SELECT {child_key},COUNT(*) FROM {table} WHERE {child_key} IN ({marks}) GROUP BY {child_key}",
                values,
            ).fetchall()
            child_counts[table] = dict(found)
    for row in rows:
        needed = 1
        for table, child_key, parent_key in rule.children:
            parent_value = row[rule.keys.index(parent_key)]
            needed += int(child_counts.get(table, {}).get(parent_value, 0))
        if needed > remaining and rule.table != "path_snapshots":
            protected += 1
            continue
        if rule.table == "path_snapshot_sync_uploads":
            try:
                custody.enter_context(upload_lock(conn, row[0]))
            except ValueError as exc:
                if not str(exc).startswith("snapshot_upload_busy:"):
                    raise
                protected += 1
                continue
        accepted.append(row)
        remaining -= needed
    if accepted:
        if rule.table == "path_snapshot_sync_uploads":
            from yoke_core.domain.project_snapshot_chunk_uploads import (
                _delete_chunk_upload_rows,
            )

            _delete_chunk_upload_rows(conn, accepted[0][0])
            deleted = {
                rule.table: 1,
                rule.children[0][0]: child_counts[rule.children[0][0]].get(
                    accepted[0][0], 0
                ),
            }
            conn.commit()
            return deleted, protected
        for table, child_key, parent_key in rule.children:
            position = rule.keys.index(parent_key)
            values = tuple(row[position] for row in accepted)
            marks = ",".join("%s" for _ in values)
            result = _execute(
                conn,
                policy,
                deadline,
                f"DELETE FROM {table} WHERE {child_key} IN ({marks})",
                values,
            )
            deleted[table] = result.rowcount
        # Eligibility is rechecked inside the DELETE itself. A graph whose
        # parent stopped qualifying after its children went rolls back whole.
        clause, values = _key_where(rule.keys, accepted)
        result = _execute(
            conn,
            policy,
            deadline,
            f"DELETE FROM {rule.table} t WHERE {clause} AND ({rule.where})",
            (*values, *rule.params),
        )
        if rule.children and result.rowcount != len(accepted):
            conn.rollback()
            return {}, protected + len(accepted)
        protected += len(accepted) - result.rowcount
        deleted[rule.table] = result.rowcount
    conn.commit()
    return deleted, protected


def _table_pass(conn, policy, deadline, rule, apply):
    """One cohort: select (row-locking on apply), then delete or preview."""
    if apply:
        _hold_cohort(conn, policy, deadline, rule)
    columns = ",".join(f"t.{key}" for key in rule.keys)
    cohort_limit = (
        1
        if rule.table in ("path_snapshots", "path_snapshot_sync_uploads")
        else policy.batch_rows
    )
    lock = (
        " FOR UPDATE OF t SKIP LOCKED"
        if apply and db_backend.connection_is_postgres(conn)
        else ""
    )
    rows = _execute(
        conn,
        policy,
        deadline,
        f"SELECT {columns} FROM {rule.table} t WHERE {rule.where} ORDER BY {columns} LIMIT %s{lock}",
        (*rule.params, cohort_limit + 1),
    ).fetchall()
    partial = len(rows) > cohort_limit
    rows = rows[:cohort_limit]
    protected = None
    deleted, graph_protected = ({}, 0)
    if apply:
        with ExitStack() as custody:
            deleted, graph_protected = _delete_cohort(
                conn, policy, deadline, rule, rows, custody
            )
    else:
        # Preview only: a bounded sample, never a full-table count. Apply
        # passes skip it; it would rescan the same rows on every cohort.
        protected = _execute(
            conn,
            policy,
            deadline,
            f"SELECT COUNT(*) FROM (SELECT * FROM {rule.table} LIMIT %s) t WHERE NOT COALESCE(({rule.where}),FALSE)",
            (policy.batch_rows, *rule.params),
        ).fetchone()[0]
        protected = min(protected, policy.batch_rows)
        conn.rollback()
    return {
        "table": rule.table,
        "eligible": len(rows),
        "eligible_partial": partial,
        "deleted": deleted,
        "protected": protected,
        "protected_partial": protected is not None,
        "protected_graphs": graph_protected,
        "protection": rule.reason,
        "graph_budget_reason": "graph/custody exceeds bounded transaction; retained"
        if graph_protected
        else None,
    }
