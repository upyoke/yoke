"""Reviewed, transactional repairs of bounded control-plane rows."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from psycopg import sql
from yoke_contracts.operator_data_repair import repair_review_digest

from yoke_core.domain import operator_data_repair_audit as audit
from yoke_core.domain.operator_data_repair_values import (
    is_sensitive_key,
    redacted_json_safe,
)
from yoke_core.domain.operator_data_repair_items import (
    public_snapshots,
    resolve_item_plan,
    snapshot_keys,
)
from yoke_core.domain.operator_data_repair_sql import (
    RepairRefusal,
    SAFE_TYPES,
    identifier,
    validate_sql,
)


class RepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(min_length=1)
    sql: str = Field(min_length=1, max_length=100000)
    table: str
    key_columns: list[str] = Field(min_length=1)
    before: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    after: list[dict[str, Any]] = Field(max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)


def review_digest(plan: RepairPlan) -> str:
    return repair_review_digest(plan.model_dump())


def _rows_by_key(rows, keys):
    indexed = {}
    for row in rows:
        try:
            key = tuple(
                json.dumps(row[name], sort_keys=True, allow_nan=False) for name in keys
            )
        except (KeyError, TypeError, ValueError):
            raise RepairRefusal(
                "repair_row_identity_invalid",
                "Every row must carry its exact primary key values.",
            ) from None
        if any(row[name] is None for name in keys) or key in indexed:
            raise RepairRefusal(
                "repair_row_identity_invalid",
                "Primary keys must be non-null and unique in each snapshot.",
            )
        indexed[key] = json.dumps(
            row, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    return indexed


def validate_plan(plan: RepairPlan, reviewed_sha256: str):
    if review_digest(plan) != reviewed_sha256:
        raise RepairRefusal(
            "repair_review_changed",
            "The review digest does not match this repair document; review the current document and compute its digest.",
        )
    stmt = validate_sql(plan.sql, plan.table, plan.key_columns)
    if set(snapshot_keys(plan)) & set(stmt.changed_columns):
        raise RepairRefusal(
            "repair_key_mutation",
            "Public references identify immutable item keys; change only non-key columns.",
        )
    keys = snapshot_keys(plan)
    columns = sorted(plan.before[0])
    if not set(keys).issubset(columns) or not set(stmt.changed_columns).issubset(
        columns
    ):
        raise RepairRefusal(
            "repair_snapshot_incomplete",
            "Snapshots must include every primary key and assigned column; use public_ref for item_id, <role>_public_ref for <role>_item_id, and epic_public_ref for epic_id (PREFIX-N values).",
        )
    for column in columns:
        identifier(column)
        if is_sensitive_key(column):
            raise RepairRefusal(
                "repair_sensitive_evidence",
                "Secret-bearing columns require their capability-owned command, not row repair.",
            )
    for row in plan.before + plan.after:
        if sorted(row) != columns or redacted_json_safe(row) != row:
            raise RepairRefusal(
                "repair_snapshot_invalid",
                "Use identical JSON-safe column sets without secret-bearing values in every snapshot.",
            )
    before = _rows_by_key(plan.before, keys)
    after = _rows_by_key(plan.after, keys)
    if (stmt.delete and after) or (not stmt.delete and before.keys() != after.keys()):
        raise RepairRefusal(
            "repair_after_identity_mismatch",
            "UPDATE preserves the exact key set; DELETE requires an empty after snapshot.",
        )
    return stmt, columns


def _table_contract(conn, plan, columns, project_id: int):
    table = "public." + plan.table
    # A table lock closes races between predicate review and execution, including
    # inserts; no source lane or item claim is involved in operator authority.
    conn.execute(
        sql.SQL("LOCK TABLE ONLY {} IN SHARE ROW EXCLUSIVE MODE").format(
            sql.Identifier("public", plan.table)
        )
    )
    row = conn.execute(
        "SELECT c.relkind, c.relrowsecurity, "
        "EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal), "
        "EXISTS(SELECT 1 FROM pg_rewrite r WHERE r.ev_class=c.oid), "
        "EXISTS(SELECT 1 FROM pg_inherits i WHERE i.inhparent=c.oid OR i.inhrelid=c.oid) "
        "FROM pg_class c WHERE c.oid=%s::regclass",
        (table,),
    ).fetchone()
    if row is None or row[0] != "r" or any(row[1:]):
        raise RepairRefusal(
            "repair_table_effects_refused",
            "Use a plain table without RLS, user triggers, rules, or inheritance; those effects need governed migration review.",
        )
    cascades = conn.execute(
        "SELECT 1 FROM pg_constraint WHERE contype='f' AND confrelid=%s::regclass "
        "AND (confdeltype NOT IN ('a','r') OR confupdtype NOT IN ('a','r')) LIMIT 1",
        (table,),
    ).fetchone()
    if cascades:
        raise RepairRefusal(
            "repair_cascade_refused",
            "Cascading foreign-key effects need governed migration review.",
        )
    keys = conn.execute(
        "SELECT a.attname FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum "
        "WHERE i.indrelid=%s::regclass AND i.indisprimary ORDER BY k.ord",
        (table,),
    ).fetchall()
    if [row[0] for row in keys] != plan.key_columns:
        raise RepairRefusal(
            "repair_primary_key_mismatch",
            "Declare the table's complete primary key in catalog order.",
        )
    types = conn.execute(
        "SELECT a.attname, n.nspname, t.typname FROM pg_attribute a "
        "JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace n ON n.oid=t.typnamespace "
        "WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped",
        (table,),
    ).fetchall()
    declared = {name: (schema, typename) for name, schema, typename in types}
    if "project_id" in declared and any(
        row.get("project_id") != project_id for row in plan.before
    ):
        raise RepairRefusal(
            "repair_project_scope_mismatch",
            "This table is project-owned: every before row must carry project_id equal to the document's project; split the repair per project.",
        )
    if any(
        declared.get(name, (None, None))[0] != "pg_catalog"
        or declared[name][1] not in SAFE_TYPES
        for name in columns
    ):
        raise RepairRefusal(
            "repair_column_type_refused",
            "Snapshot columns must use documented built-in scalar or JSON types.",
        )


def _snapshot(conn, plan, columns, predicate: str, params=()):
    query = sql.SQL("SELECT {} FROM ONLY {} WHERE {} LIMIT 1001").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.Identifier("public", plan.table),
        sql.SQL(predicate),
    )
    rows = (conn.execute(query, params) if params else conn.execute(query)).fetchall()
    if len(rows) > 1000:
        raise RepairRefusal(
            "repair_row_limit",
            "The predicate selects more than 1000 rows; narrow the repair.",
        )
    if any(
        isinstance(value, (str, dict, list)) and redacted_json_safe(value) != value
        for row in rows
        for value in row
    ):
        raise RepairRefusal(
            "repair_sensitive_evidence",
            "Selected rows contain secret-bearing JSON; use their capability-owned mutation instead.",
        )
    result = [
        {name: redacted_json_safe(value, column_name=name) for name, value in zip(columns, row)}
        for row in rows
    ]
    return result


def run_repair(
    conn,
    plan: RepairPlan,
    *,
    reviewed_sha256: str,
    actor_id: int,
    project_id: int,
    dry_run: bool,
):
    stmt, columns = validate_plan(plan, reviewed_sha256)
    if plan.table in {
        "migration_audit",
        "applied_migrations",
        "migration_content_adoptions",
    }:
        raise RepairRefusal(
            "repair_audit_target_refused",
            "Audit and migration ledgers cannot repair themselves; escalate to the control-plane operator.",
        )
    sql_hash = hashlib.sha256(plan.sql.encode()).hexdigest()
    audit_id = audit.begin(
        conn,
        plan=plan,
        actor_id=actor_id,
        sql_hash=sql_hash,
        review_hash=reviewed_sha256,
    )
    before, after, refs = [], [], {}
    try:
        conn.execute("SET LOCAL search_path = pg_catalog")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        conn.execute("SET LOCAL lock_timeout = '5s'")
        plan, refs = resolve_item_plan(conn, plan, project_id)
        if refs:
            stmt = validate_sql(plan.sql, plan.table, plan.key_columns)
            columns = sorted(plan.before[0])
        _table_contract(
            conn, plan, sorted(set(columns) | set(stmt.read_columns)), project_id
        )
        before = _snapshot(conn, plan, columns, stmt.predicate)
        if _rows_by_key(before, plan.key_columns) != _rows_by_key(
            plan.before, plan.key_columns
        ):
            raise RepairRefusal(
                "repair_before_changed",
                "The current targeted rows differ from the reviewed before snapshot; read current values and review again.",
            )
        affected = conn.execute(stmt.mutation).fetchall()
        expected_keys = {
            tuple(row[key] for key in plan.key_columns) for row in plan.before
        }
        affected_keys = {tuple(redacted_json_safe(value) for value in row) for row in affected}
        if len(affected) != len(expected_keys) or affected_keys != expected_keys:
            raise RepairRefusal(
                "repair_affected_rows_changed",
                "The mutation did not affect exactly the reviewed primary keys; read current rows and review again before retrying.",
            )
        predicate = " OR ".join(
            "("
            + " AND ".join(identifier(key) + " = %s" for key in plan.key_columns)
            + ")"
            for _ in plan.before
        )
        params = tuple(row[key] for row in plan.before for key in plan.key_columns)
        after = _snapshot(conn, plan, columns, predicate, params)
        if _rows_by_key(after, plan.key_columns) != _rows_by_key(
            plan.after, plan.key_columns
        ):
            raise RepairRefusal(
                "repair_after_mismatch",
                "The observed result differs from the reviewed after snapshot; correct the SQL or expected result.",
            )
        if dry_run:
            conn.rollback()
        audit.finish(
            conn,
            audit_id,
            state="test_verified" if dry_run else "completed",
            before=public_snapshots(conn, before, refs),
            after=public_snapshots(conn, after, refs),
        )
    except Exception as exc:
        conn.rollback()
        code = exc.code if isinstance(exc, RepairRefusal) else "repair_execution_failed"
        # Database messages may echo secret SQL literals; durable diagnosis uses
        # SQLSTATE and the review hash instead of raw server exception text.
        reason = (
            str(exc)
            if isinstance(exc, RepairRefusal)
            else f"SQLSTATE {getattr(exc, 'sqlstate', None) or 'unknown'}; inspect the reviewed SQL and current schema, then retry."
        )
        try:
            audit.finish(
                conn,
                audit_id,
                state="live_apply_failed",
                before=public_snapshots(conn, before, refs),
                after=public_snapshots(conn, after, refs),
                reason=code + ": " + reason,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise RepairRefusal(
                "repair_outcome_unavailable",
                f"Repair audit {audit_id} needs operator reconciliation; read migration_audit before retrying, because the final commit outcome may be unknown.",
            ) from None
        raise RepairRefusal(code, f"Audit {audit_id}: {reason}") from None
    try:
        conn.commit()
    except Exception:
        raise RepairRefusal(
            "repair_commit_outcome_unknown",
            f"Audit {audit_id}: the final commit could not be confirmed; read its durable outcome and current row values before any retry.",
        ) from None
    return {
        "audit_id": audit_id,
        "outcome": "dry_run_rolled_back" if dry_run else "completed",
        "sql_sha256": sql_hash,
        "review_sha256": reviewed_sha256,
        "row_count": len(before),
    }
