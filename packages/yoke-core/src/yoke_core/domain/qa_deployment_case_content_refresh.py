"""Let a corrected plan case reach a member whose frozen row was discharged.

Stage materialization is idempotent per plan: once a member has rows for a
plan, materializing again returns them untouched. That is right while those
rows still answer for the plan, and wrong the moment one is discharged and
the plan's case is then corrected. The member is left with no executable
case -- the discharged row satisfies idempotency, so the corrected content
never arrives -- and the only way through was to publish a whole new plan
carrying the same fixed probe.

The decision here is narrow on purpose. A fresh row is warranted only when
both halves hold: the existing row no longer answers (waived, superseded, or
settled ``fail``), and the plan's case content has actually changed since it
was materialized. An unchanged case stays idempotent however its row was
discharged, so re-running a plan never quietly manufactures work.

Content identity is computed from the case itself rather than stored, so no
column or table carries it: the fields a runner actually executes are hashed,
and the resulting key distinguishes the corrected row from the frozen one it
will later be linked to by :mod:`qa_requirement_supersession`. The distinct
key is also what makes the second row possible at all -- a materialized case
is unique on ``(run, stage, member, plan_id, plan_case_key, host_baseline,
target)``, so a replacement sharing the original's key could not be inserted.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_obligation_settlement import obligation_settled


#: The fields that decide what a runner will actually do. Anything outside
#: this set may differ without making the frozen row the wrong case.
_CONTENT_FIELDS = (
    "method_id",
    "method_config",
    "instructions",
    "expected_outcome",
)

#: Separates a corrected case's key from the content digest that makes it
#: distinct. Chosen because no authored case key may contain it.
REFRESH_KEY_SEPARATOR = "@"

_DIGEST_LENGTH = 12


def _normalized(value: Any) -> Any:
    """Compare stored JSON text and decoded payloads as the same content."""
    if isinstance(value, Mapping):
        return {str(key): _normalized(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "["):
            try:
                return _normalized(json.loads(text))
            except (TypeError, ValueError):
                return value
        return value
    return value


def case_content_digest(case: Mapping[str, Any]) -> str:
    """Stable identity for the executable content of one case."""
    payload = {field: _normalized(case.get(field)) for field in _CONTENT_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def base_case_key(plan_case_key: str) -> str:
    """The authored key behind a possibly-refreshed one."""
    return str(plan_case_key).split(REFRESH_KEY_SEPARATOR, 1)[0]


def refreshed_case_key(plan_case_key: str, digest: str) -> str:
    """The key a corrected case materializes under, beside the frozen row."""
    return f"{base_case_key(plan_case_key)}{REFRESH_KEY_SEPARATOR}{digest}"


def _discharged_or_failed(conn: Any, row: Mapping[str, Any]) -> bool:
    """True when this row no longer answers for its case."""
    if obligation_settled(row):
        return True
    verdict = query_rows(
        conn,
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(row["id"]),),
    )
    return bool(verdict) and str(verdict[0]["verdict"] or "") == "fail"


def refreshed_case_keys(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    plan_id: int,
    execution_target_digest: str,
    cases: list[Mapping[str, Any]],
) -> dict[str, str]:
    """Map each case key that needs a fresh row to the key it takes.

    Empty when every case is either still answered by its row or unchanged
    since it was materialized -- which is the ordinary idempotent outcome.
    """
    rows = query_rows(
        conn,
        "SELECT id,plan_case_key,method_id,method_config,instructions,"
        "expected_outcome,waived_at,superseded_by_requirement_id "
        "FROM qa_requirements WHERE deployment_run_id=%s AND deployment_stage=%s "
        "AND COALESCE(deployment_member_item_id,0)=%s AND plan_id=%s "
        "AND execution_target_digest=%s ORDER BY id",
        (
            run_id,
            stage_name,
            member_item_id or 0,
            int(plan_id),
            execution_target_digest,
        ),
    )
    if not rows:
        return {}
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(base_case_key(row["plan_case_key"]), []).append(dict(row))

    refreshed: dict[str, str] = {}
    for case in cases:
        key = str(case["case_key"])
        materialized = by_key.get(key)
        if not materialized:
            # Never materialized here; ordinary insertion handles it.
            continue
        digest = case_content_digest(case)
        if any(case_content_digest(row) == digest for row in materialized):
            # This exact content is already present, discharged or not.
            continue
        if not all(_discharged_or_failed(conn, row) for row in materialized):
            # Something still answers for this case; a correction would be
            # competing with live work rather than replacing spent work.
            continue
        refreshed[key] = refreshed_case_key(key, digest)
    return refreshed


__all__ = [
    "REFRESH_KEY_SEPARATOR",
    "base_case_key",
    "case_content_digest",
    "refreshed_case_key",
    "refreshed_case_keys",
]
