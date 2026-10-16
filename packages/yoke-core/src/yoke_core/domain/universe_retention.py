"""Existing-schema settings and bounded, output-only universe pruning."""

from __future__ import annotations

from datetime import datetime
from contextlib import ExitStack
import json
import time

from yoke_contracts.retention_defaults import RETENTION_KEY
from yoke_contracts.timestamps import as_utc, format_instant, utc_now
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


def _lock_tables(conn, policy, deadline, rule):
    if not db_backend.connection_is_postgres(conn):
        return
    tables = sorted(
        {"universe_settings", rule.table, *rule.locks, *(c[0] for c in rule.children)}
    )
    # The same bounded custody covers reference/owner writers and eligibility
    # rechecks. It lasts only for this one committed graph/cohort.
    _execute(
        conn,
        policy,
        deadline,
        "LOCK TABLE " + ",".join(tables) + " IN SHARE ROW EXCLUSIVE MODE",
    )
    if rule.table == "path_snapshots":
        # Native reader locks participate even when an older serving build is
        # still present during rollout. No new reader protocol is required.
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
        clause, values = _key_where(rule.keys, accepted)
        result = _execute(
            conn, policy, deadline, f"DELETE FROM {rule.table} WHERE {clause}", values
        )
        deleted[rule.table] = result.rowcount
    conn.commit()
    return deleted, protected


def _table_pass(conn, policy, deadline, rule, apply):
    if apply:
        _lock_tables(conn, policy, deadline, rule)
        current, _ = read_policy(conn)
        if current.digest != policy.digest:
            raise ValueError(
                "retention_policy_changed: recovery: review settings and rerun universe prune."
            )
    columns = ",".join(f"t.{key}" for key in rule.keys)
    cohort_limit = (
        1
        if rule.table in ("path_snapshots", "path_snapshot_sync_uploads")
        else policy.batch_rows
    )
    rows = _execute(
        conn,
        policy,
        deadline,
        f"SELECT {columns} FROM {rule.table} t WHERE {rule.where} ORDER BY {columns} LIMIT %s",
        (*rule.params, cohort_limit + 1),
    ).fetchall()
    partial = len(rows) > cohort_limit
    rows = rows[:cohort_limit]
    # This is explicitly a bounded sample, never a prerequisite full-table
    # count. The eligibility search itself is guarded by statement_timeout.
    protected = _execute(
        conn,
        policy,
        deadline,
        f"SELECT COUNT(*) FROM (SELECT * FROM {rule.table} LIMIT %s) t WHERE NOT COALESCE(({rule.where}),FALSE)",
        (policy.batch_rows, *rule.params),
    ).fetchone()[0]
    deleted, graph_protected = ({}, 0)
    if apply:
        with ExitStack() as custody:
            deleted, graph_protected = _delete_cohort(
                conn, policy, deadline, rule, rows, custody
            )
    else:
        conn.rollback()
    return {
        "table": rule.table,
        "eligible": len(rows),
        "eligible_partial": partial,
        "deleted": deleted,
        "protected": min(protected, policy.batch_rows),
        "protected_partial": True,
        "protected_graphs": graph_protected,
        "protection": rule.reason,
        "graph_budget_reason": "graph/custody exceeds bounded transaction; retained"
        if graph_protected
        else None,
    }


def prune_pass(conn, request):
    from yoke_core.domain.retention_table_policies import policies
    from yoke_core.domain.retention_message_graphs import policies as graph_policies
    from yoke_core.domain.retention_operational_policy import upload_policy
    from yoke_core.domain.universe_retention_snapshots import snapshot_policy

    current = utc_now()
    cutoff = as_utc(request.cutoff) if request.cutoff else current
    if cutoff > current:
        raise ValueError(
            "retention_cutoff_in_future: recovery: rerun the command with the server's current UTC cutoff."
        )
    policy, result = read_retention(conn, cutoff)
    if request.expected_digest and request.expected_digest != policy.digest:
        raise ValueError(
            "retention_policy_changed: recovery: review universe retention get, then rerun prune with its new policy."
        )
    rules = (
        policies(policy, cutoff)
        + graph_policies(policy, cutoff)
        + [snapshot_policy(), upload_policy(policy, cutoff)]
    )
    if request.table_index >= len(rules):
        raise ValueError(
            "retention_table_index_invalid: recovery: rerun universe prune from the beginning."
        )
    # End read transactions before the cohort's bounded custody starts.
    conn.rollback()
    deadline = time.monotonic() + policy.pass_seconds
    result.update(
        tables=[],
        next_table_index=request.table_index,
        cycle_complete=False,
        failure=None,
    )
    for index in range(request.table_index, len(rules)):
        rule = rules[index]
        if time.monotonic() >= deadline:
            break
        try:
            row = _table_pass(conn, policy, deadline, rule, request.apply)
            result["tables"].append(row)
        except Exception as exc:
            conn.rollback()
            code = getattr(exc, "sqlstate", "")
            budget = isinstance(exc, TimeoutError) or code in ("57014", "55P03")
            policy_error = isinstance(exc, ValueError) and str(exc).startswith(
                ("retention_policy_changed:", "retention_policy_invalid:")
            )
            result["failure"] = {
                "code": str(exc).partition(":")[0]
                if policy_error
                else ("retention_budget_stop" if budget else "retention_table_failed"),
                "table": rule.table,
                "reason": "statement/lock/pass budget reached"
                if budget
                else (
                    str(exc)
                    if policy_error
                    else f"database operation refused ({code or type(exc).__name__}); no uncommitted cohort was applied"
                ),
                "recovery": "Earlier committed batches remain committed. Rerun universe prune; if repeated, ask the universe administrator to inspect this table.",
            }
            return result
        result["next_table_index"] = (index + 1) % len(rules)
        if index + 1 == len(rules):
            result["cycle_complete"] = True
            break
    return result
