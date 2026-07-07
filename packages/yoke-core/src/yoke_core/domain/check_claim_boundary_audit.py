"""Read-only scanner for claim-boundary violations in the events ledger.

Findings cover mutating function attribution, claim-release overrides,
and path-claim amendments against the live work-claim holder at event
time. The scanner never mutates rows or emits repair events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, List, Optional

from yoke_core.domain.check_claim_boundary_audit_correlation import (
    extract_function_response,
    has_correlated_function_call,
)
from yoke_core.domain.check_claim_boundary_audit_cutoff import (
    select_events as _select_events,
)
from yoke_core.domain.check_claim_boundary_audit_rows import (
    ensure_row_factory as _ensure_row_factory,
)
from yoke_core.domain.check_claim_boundary_audit_select import (
    select_unattributed_harness_events,
)
from yoke_core.domain.check_claim_boundary_audit_path_claims import (
    path_claim_event_has_matching_item_owner,
)
from yoke_core.domain.schema_common import _table_exists as _schema_table_exists


_MUTATING_FUNCTION_PREFIXES = (
    "items.structured_field",
    "items.section",
    "items.scalar",
    "items.progress_log",
    "lifecycle.transition",
    "workflow_item.epic_task",
    "workflow_item.epic_progress_note",
    "db_claim",
    "qa.requirement",
    "qa.run",
)
_NON_MUTATING_FUNCTION_NAMES = ("qa.requirement.get", "qa.requirement.list", "qa.run.list")
@dataclass(frozen=True)
class Finding:
    severity: str
    finding_class: str
    event_id: int
    item_id: Optional[int]
    holder_session_id: Optional[str]
    caller_session_id: Optional[str]
    mutation_surface: str
    rationale: str


def _table_present(conn: Any, name: str) -> bool:
    return _schema_table_exists(conn, name)


def _envelope(row: Any) -> dict:
    raw = row["envelope"]
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_mutating_function(name: str) -> bool:
    if name in _NON_MUTATING_FUNCTION_NAMES:
        return False
    return any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in _MUTATING_FUNCTION_PREFIXES
    )


def _coerce_item_id(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).replace("YOK-", ""))
    except (ValueError, TypeError):
        return None


def _context(row: Any) -> dict:
    ctx = _envelope(row).get("context", {})
    return ctx if isinstance(ctx, dict) else {}


def _live_claim_holder_at(
    conn: Any,
    item_id: int,
    created_at: str,
) -> Optional[str]:
    from yoke_core.domain import db_backend

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cur = conn.execute(
        f"""
        SELECT session_id
        FROM work_claims
        WHERE target_kind='item'
          AND item_id={p}
          AND claimed_at <= {p}
          AND (released_at IS NULL OR released_at >= {p})
        ORDER BY claimed_at DESC
        LIMIT 1
        """,
        (item_id, created_at, created_at),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _preview_surface_and_item(row: Any) -> tuple[str, Optional[int]]:
    detail = (_envelope(row).get("context") or {}).get("detail") or {}
    fn, item = extract_function_response(str(detail.get("tool_response_preview") or ""))
    return fn, item if item is not None else _coerce_item_id(row["item_id"])


def _classify_holder_caller(
    *,
    finding_class: str,
    event_id: int,
    item_id: Optional[int],
    holder: Optional[str],
    caller: Optional[str],
    surface: str,
    no_caller_rationale: str,
    no_holder_rationale: str,
    mismatch_rationale: str,
) -> Optional[Finding]:
    if not caller:
        return Finding(
            severity="WARN", finding_class=finding_class,
            event_id=event_id, item_id=item_id,
            holder_session_id=holder, caller_session_id=None,
            mutation_surface=surface, rationale=no_caller_rationale,
        )
    if holder is None:
        return Finding(
            severity="WARN", finding_class=finding_class,
            event_id=event_id, item_id=item_id,
            holder_session_id=None, caller_session_id=caller,
            mutation_surface=surface, rationale=no_holder_rationale,
        )
    if holder != caller:
        return Finding(
            severity="FAIL", finding_class=finding_class,
            event_id=event_id, item_id=item_id,
            holder_session_id=holder, caller_session_id=caller,
            mutation_surface=surface, rationale=mismatch_rationale,
        )
    return None


def scan_function_call_attribution(
    conn: Any,
    *,
    since: Optional[str] = None,
) -> List[Finding]:
    if not _table_present(conn, "events"):
        return []
    if not _table_present(conn, "work_claims"):
        return []
    _ensure_row_factory(conn)
    findings: List[Finding] = []
    for row in _select_events(conn, "YokeFunctionCalled", since):
        ctx = _context(row)
        fn_name = str(ctx.get("function") or "")
        if not _is_mutating_function(fn_name):
            continue
        item_id_int = _coerce_item_id(row["item_id"])
        if item_id_int is None:
            continue
        caller = row["session_id"]
        holder = _live_claim_holder_at(
            conn, item_id_int, row["created_at"],
        )
        finding = _classify_holder_caller(
            finding_class="function_call_attribution_mismatch",
            event_id=int(row["id"]),
            item_id=item_id_int,
            holder=holder,
            caller=caller,
            surface=fn_name,
            no_caller_rationale=(
                "caller session not recorded on the event — "
                "incomplete attribution evidence"
            ),
            no_holder_rationale=(
                "no live work claim recorded at event time — cannot "
                "verify authorisation"
            ),
            mismatch_rationale=(
                "function call recorded under a session that did not "
                "hold the work claim at event time"
            ),
        )
        if finding is not None:
            findings.append(finding)
    for row in select_unattributed_harness_events(
        conn, since, mutating_prefixes=_MUTATING_FUNCTION_PREFIXES,
    ):
        flags = str(row["anomaly_flags"] or "")
        if "unattributed" not in flags:
            continue
        fn_name, item_id_int = _preview_surface_and_item(row)
        if not _is_mutating_function(fn_name):
            continue
        if has_correlated_function_call(
            conn, harness_row=row, function_name=fn_name, item_id=item_id_int,
        ):
            continue
        findings.append(Finding(
            severity="WARN",
            finding_class="function_call_attribution_mismatch",
            event_id=int(row["id"]),
            item_id=item_id_int,
            holder_session_id=None,
            caller_session_id=row["session_id"],
            mutation_surface=fn_name,
            rationale=(
                "ambient HarnessToolCallCompleted returned a mutating "
                "function response but durable YokeFunctionCalled "
                "attribution is not correlated"
            ),
        ))
    return findings


def scan_non_operator_claim_release_overrides(
    conn: Any,
    *,
    since: Optional[str] = None,
) -> List[Finding]:
    if not _table_present(conn, "events"):
        return []
    _ensure_row_factory(conn)
    findings: List[Finding] = []
    for row in _select_events(conn, "ItemClaimReleaseOverride", since):
        ctx = _context(row)
        prior_owner = ctx.get("prior_owner_session_id")
        rationale_text = str(ctx.get("operator_rationale") or "").strip()
        caller = row["session_id"]
        item_id_int = _coerce_item_id(row["item_id"])
        if not rationale_text:
            findings.append(Finding(
                severity="WARN",
                finding_class="non_operator_claim_release_override",
                event_id=int(row["id"]),
                item_id=item_id_int,
                holder_session_id=prior_owner,
                caller_session_id=caller,
                mutation_surface="ItemClaimReleaseOverride",
                rationale="override missing operator_rationale evidence",
            ))
            continue
        if prior_owner and prior_owner != caller:
            findings.append(Finding(
                severity="FAIL",
                finding_class="non_operator_claim_release_override",
                event_id=int(row["id"]),
                item_id=item_id_int,
                holder_session_id=prior_owner,
                caller_session_id=caller,
                mutation_surface="ItemClaimReleaseOverride",
                rationale=(
                    "cross-session claim release without operator-only "
                    "attribution; caller != prior owner"
                ),
            ))
    return findings


def scan_path_claim_amendments_without_owning_claim(
    conn: Any,
    *,
    since: Optional[str] = None,
) -> List[Finding]:
    if not _table_present(conn, "events"):
        return []
    if not _table_present(conn, "work_claims"):
        return []
    _ensure_row_factory(conn)
    findings: List[Finding] = []
    for row in _select_events(conn, "PathClaimAmended", since):
        item_id_int = _coerce_item_id(row["item_id"])
        if item_id_int is None:
            continue
        # PathClaimAmended carries path-claim provenance. For item-owned
        # claims, the claim row is the authority; event.session_id may be the
        # registering session after a live work-claim handoff.
        if path_claim_event_has_matching_item_owner(
            conn, row, item_id=item_id_int,
        ):
            continue
        caller = row["session_id"]
        holder = _live_claim_holder_at(
            conn, item_id_int, row["created_at"],
        )
        finding = _classify_holder_caller(
            finding_class="path_claim_mutation_without_owning_claim",
            event_id=int(row["id"]),
            item_id=item_id_int,
            holder=holder,
            caller=caller,
            surface="PathClaimAmended",
            no_caller_rationale=(
                "caller session not recorded on the event — "
                "incomplete attribution evidence"
            ),
            no_holder_rationale=(
                "path-claim amendment recorded without any live work "
                "claim on the item — cannot verify ownership"
            ),
            mismatch_rationale=(
                "path-claim amendment recorded under a session that "
                "did not hold the live work claim at event time"
            ),
        )
        if finding is not None:
            findings.append(finding)
    return findings


def scan_all(
    conn: Any,
    *,
    since: Optional[str] = None,
) -> List[Finding]:
    return [
        *scan_function_call_attribution(conn, since=since),
        *scan_non_operator_claim_release_overrides(conn, since=since),
        *scan_path_claim_amendments_without_owning_claim(conn, since=since),
    ]

__all__ = [
    "Finding",
    "scan_function_call_attribution",
    "scan_non_operator_claim_release_overrides",
    "scan_path_claim_amendments_without_owning_claim",
    "scan_all",
]
