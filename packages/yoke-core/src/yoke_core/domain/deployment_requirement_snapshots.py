"""Immutable QA inputs captured when a deployment run starts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_requirement_snapshot_format import (
    CASE_FIELDS,
    PLAN_CASE_COLUMNS,
    PLAN_FIELDS,
    REQUIREMENT_FIELDS,
    semantic_row,
)
from yoke_core.domain.qa_converging_columns import converged_select
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.qa_plan_attachment_reads import (
    live_item_attachment_sql,
    retracted_item_plan_ids,
)
from yoke_core.domain.qa_obligation_settlement import requirement_retracted_at_select
from yoke_core.domain.project_identity import render_item_ref
from yoke_contracts.public_ref import ITEM_NOT_FOUND


SNAPSHOT_SCHEMA = 1
SELECTION_SCHEMA = 1


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row_dict(cursor: Any, row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [str(getattr(col, "name", None) or col[0]) for col in cursor.description]
    return dict(zip(columns, row))


def _positive_ids(values: Iterable[Any], *, field: str) -> list[int]:
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must contain positive integer ids")
        normalized.append(int(value))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicate ids")
    return sorted(normalized)


def requirement_selection(
    *,
    requirement_ids: Iterable[int] = (),
    plan_ids: Iterable[int] = (),
) -> str:
    """Encode an explicit per-member requirement selection."""
    return _canonical(
        {
            "schema": SELECTION_SCHEMA,
            "requirement_ids": _positive_ids(requirement_ids, field="requirement_ids"),
            "plan_ids": _positive_ids(plan_ids, field="plan_ids"),
        }
    )


def _selection(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {
            "schema": SELECTION_SCHEMA,
            "requirement_ids": [],
            "plan_ids": [],
        }
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("member requirement_selection is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("member requirement_selection must be a JSON object")
    if set(decoded) != {"schema", "requirement_ids", "plan_ids"}:
        raise ValueError(
            "member requirement_selection must contain only schema, "
            "requirement_ids and plan_ids"
        )
    if decoded.get("schema") != SELECTION_SCHEMA:
        raise ValueError(
            f"member requirement_selection schema must be {SELECTION_SCHEMA}"
        )
    return {
        "schema": SELECTION_SCHEMA,
        "requirement_ids": _positive_ids(
            decoded.get("requirement_ids") or [], field="requirement_ids"
        ),
        "plan_ids": _positive_ids(decoded.get("plan_ids") or [], field="plan_ids"),
    }


def _plan_snapshot(
    conn: Any,
    plan_id: int,
    *,
    project_id: int,
    case_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    marker = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    cursor = conn.execute(
        f"SELECT {','.join(PLAN_FIELDS)},retired_at "
        f"FROM qa_plans WHERE id={marker}{lock}",
        (int(plan_id),),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"QA plan {plan_id} not found")
    raw_plan = _row_dict(cursor, row)
    plan = semantic_row(raw_plan, PLAN_FIELDS)
    if int(plan["project_id"]) != int(project_id):
        raise ValueError(f"QA plan {plan_id} belongs to another project")
    if raw_plan.get("retired_at") is not None:
        raise ValueError(f"QA plan {plan_id} is retired")
    requested = [str(value) for value in (case_keys or ())]
    if any(not value for value in requested) or len(requested) != len(set(requested)):
        raise ValueError(f"QA plan {plan_id} case_keys must be unique non-empty names")
    case_columns = converged_select(conn, "qa_plan_cases", PLAN_CASE_COLUMNS, "c")
    cursor = conn.execute(
        f"SELECT {case_columns},m.name AS method_name,m.runner_id,"
