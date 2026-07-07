"""Dispatch-time freshness check for charge/resume offers."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

from . import db_backend
from .db_helpers import connect
from .frontier_classify import classify_next_action
from .scheduler_events import emit_scheduler_offer_skipped
from .scheduler_skip_reasons import SKIP_REASON_STALE_LIFECYCLE
from .session_decision_lane_gate import evaluate_lane_gate
from .sessions_lifecycle_release import release_item_claim_for_execution
from .sessions_offer_revalidation import holder_session_for_item, normalize_item_id, revalidate_candidate_status
from .sessions_queries_chain import append_chain_skip_entry
_logger = logging.getLogger(__name__)

_SERVICEABLE_STEPS = frozenset({"refine", "shepherd", "conduct", "advance", "polish", "usher"})
_ADAPTER_TO_NEXT_STEP = {
    "refine": "refine", "shepherd": "shepherd", "conduct": "conduct",
    "polish": "polish", "usher": "usher", "wait": "wait", "skip": "wait",
}

class FreshnessOutcome(str, Enum):
    UNCHANGED = "unchanged"
    UNAVAILABLE = "unavailable"
    REWRITE = "rewrite"
    UNSERVICEABLE = "unserviceable"

@dataclass(frozen=True)
class FreshnessVerdict:
    outcome: FreshnessOutcome
    current_status: Optional[str] = None
    current_next_step: Optional[str] = None
    refreshed_context: Optional[Dict[str, Any]] = None
    wait_context: Optional[Dict[str, Any]] = None

@contextmanager
def _open_conn(conn_override: Optional[Any]) -> Iterator[Optional[Any]]:
    if conn_override is not None:
        yield conn_override
        return
    conn: Optional[Any] = None
    try:
        conn = connect()
        yield conn
    except db_backend.operational_error_types() as exc:
        _logger.debug("freshness check failed to open conn: %s", exc)
        yield None
    except (FileNotFoundError, RuntimeError, *db_backend.database_error_types()) as exc:
        _logger.debug("freshness check failed to open conn: %s", exc)
        yield None
    finally:
        if conn is not None:
            try:
                conn.close()
            except db_backend.database_error_types(conn):
                pass

def _session_exists(conn: Any, session_id: str) -> bool:
    if not session_id:
        return False
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            f"SELECT 1 FROM harness_sessions WHERE session_id = {p} LIMIT 1",
            (session_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return False
    except db_backend.database_error_types(conn):
        return False
    return row is not None

def _read_item_details(
    conn: Any, item_id: str,
) -> tuple[Optional[str], Optional[str]]:
    bare = normalize_item_id(item_id)
    if bare is None:
        return None, None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT p.slug AS project, i.type FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}", (bare,),
        ).fetchone()
    except db_backend.operational_error_types(conn) as exc:
        _logger.debug("freshness check items read failed: %s", exc)
        return None, None
    except db_backend.database_error_types(conn) as exc:
        _logger.debug("freshness check items read failed: %s", exc)
        return None, None
    if row is None:
        return None, None
    keys = row.keys() if hasattr(row, "keys") else None
    if keys and "project" in keys:
        return row["project"], row["type"]
    return row[0], row[1]

def _compute_live_next_step(item_type: str, live_status: str) -> Optional[str]:
    try:
        adapter = classify_next_action(live_status, item_type=item_type or "issue")
    except ValueError:
        return None
    step = _ADAPTER_TO_NEXT_STEP.get(adapter.value)
    if step is None:
        return None
    if item_type == "issue" and step == "conduct":
        return "advance"
    return step


def _is_serviceable(
    *,
    live_next_step: str,
    supported_paths: List[str],
    execution_lane: Optional[str],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
) -> bool:
    if live_next_step not in _SERVICEABLE_STEPS:
        return False
    if supported_paths and live_next_step not in supported_paths:
        return False
    if lane_allowed_paths:
        gate = evaluate_lane_gate(
            execution_lane=execution_lane,
            required_path=live_next_step,
            lane_allowed_paths=lane_allowed_paths,
        )
        if gate.is_blocked:
            return False
    return True


def _emit_refresh_event(
    *, session_id, chain_step, project, item_id,
    expected_status, live_status, expected_next_step, live_next_step,
) -> None:
    extra = {
        "detection_phase": "dispatch", "outcome": "refreshed_in_place",
        "from_status": expected_status, "from_next_step": expected_next_step,
        "to_status": live_status, "to_next_step": live_next_step,
    }
    emit_scheduler_offer_skipped(
        session_id=session_id, skip_reason=SKIP_REASON_STALE_LIFECYCLE,
        chain_step=chain_step, project=project, item_id=item_id,
        recommended_action=live_next_step, current_status=live_status, extra=extra,
    )


def _emit_unavailable_event(
    *, session_id, chain_step, item_id, expected_status,
    expected_next_step, reason,
) -> None:
    if not session_id or not item_id:
        return
    extra = {
        "detection_phase": "dispatch", "outcome": "fail_open_unavailable",
        "from_status": expected_status, "from_next_step": expected_next_step,
        "unavailable_reason": reason,
    }
    emit_scheduler_offer_skipped(
        session_id=session_id, skip_reason=SKIP_REASON_STALE_LIFECYCLE,
        chain_step=chain_step, item_id=str(item_id),
        recommended_action=expected_next_step, extra=extra,
    )


def _record_unserviceable(
    *, conn, session_id, chain_step, project, item_id,
    expected_status, live_status, expected_next_step,
    live_next_step, release_claim,
) -> Dict[str, Any]:
    holder = holder_session_for_item(conn, item_id)
    if release_claim:
        try:
            release_item_claim_for_execution(
                conn, session_id, item_id, "offer-stale-after-claim",
            )
        except Exception as exc:
            _logger.debug("freshness release failed YOK-%s: %s", item_id, exc)

    entry: Dict[str, Any] = {
        "item_id": str(item_id),
        "skip_reason": SKIP_REASON_STALE_LIFECYCLE,
        "chain_step": chain_step,
        "expected_status": expected_status,
        "current_status": live_status,
        "expected_next_step": expected_next_step,
        "detection_phase": "dispatch",
    }
    if live_next_step is not None:
        entry["live_next_step"] = live_next_step
    if holder.get("holder_session_id"):
        entry["claim_holder_session_id"] = holder["holder_session_id"]
    try:
        append_chain_skip_entry(conn, session_id, entry)
    except db_backend.database_error_types(conn) as exc:
        _logger.debug("freshness chain-skip append failed: %s", exc)

    extra: Dict[str, Any] = {
        "detection_phase": "dispatch",
        "outcome": "released_for_handoff",
        "from_status": expected_status,
        "from_next_step": expected_next_step,
    }
    if live_next_step is not None:
        extra["live_next_step"] = live_next_step
    emit_scheduler_offer_skipped(
        session_id=session_id, skip_reason=SKIP_REASON_STALE_LIFECYCLE,
        chain_step=chain_step, project=project, item_id=str(item_id),
        recommended_action=live_next_step, current_status=live_status,
        holder_session_id=holder.get("holder_session_id"),
        claim_id=holder.get("claim_id"),
        claimed_at=holder.get("claimed_at"),
        extra=extra,
    )

    wait_ctx: Dict[str, Any] = {
        "wait_reason": "stale_lifecycle_dispatch",
        "selected_item": str(item_id),
        "from_status": expected_status,
        "to_status": live_status,
        "from_next_step": expected_next_step,
    }
    if live_next_step is not None:
        wait_ctx["live_next_step"] = live_next_step
    return wait_ctx


def _unavailable(
    *, session_id, chain_step, item_id, expected_status, expected_next_step, reason,
) -> FreshnessVerdict:
    _emit_unavailable_event(
        session_id=session_id, chain_step=chain_step, item_id=item_id,
        expected_status=expected_status, expected_next_step=expected_next_step,
        reason=reason,
    )
    return FreshnessVerdict(outcome=FreshnessOutcome.UNAVAILABLE)


def evaluate_freshness(
    *,
    item_id: Optional[str],
    expected_status: Optional[str],
    expected_next_step: Optional[str],
    scheduler_context: Optional[Dict[str, Any]],
    supported_paths: List[str],
    execution_lane: Optional[str],
    lane_allowed_paths: Optional[Dict[str, List[str]]],
    session_id: str,
    chain_step: int,
    release_claim_on_unserviceable: bool = True,
    conn_override: Optional[Any] = None,
) -> FreshnessVerdict:
    if not item_id or not expected_status or not expected_next_step:
        return FreshnessVerdict(outcome=FreshnessOutcome.UNAVAILABLE)

    with _open_conn(conn_override) as conn:
        if conn is None:
            return _unavailable(
                session_id=session_id,
                chain_step=chain_step,
                item_id=item_id,
                expected_status=expected_status,
                expected_next_step=expected_next_step,
                reason="connection_unavailable",
            )
        if not _session_exists(conn, session_id):
            return FreshnessVerdict(outcome=FreshnessOutcome.UNAVAILABLE)

        is_valid, current_status = revalidate_candidate_status(
            conn, item_id=item_id, expected_status=expected_status,
        )
        if current_status is None:
            return _unavailable(
                session_id=session_id,
                chain_step=chain_step,
                item_id=item_id,
                expected_status=expected_status,
                expected_next_step=expected_next_step,
                reason="item_status_unavailable",
            )
        if is_valid:
            return FreshnessVerdict(
                outcome=FreshnessOutcome.UNCHANGED, current_status=current_status)

        project, item_type = _read_item_details(conn, item_id)
        project = project or "yoke"
        item_type = item_type or (scheduler_context or {}).get("item_type") or "issue"
        live_next_step = _compute_live_next_step(item_type, current_status)
        serviceable = (
            live_next_step is not None
            and live_next_step != "wait"
            and _is_serviceable(
                live_next_step=live_next_step,
                supported_paths=supported_paths,
                execution_lane=execution_lane,
                lane_allowed_paths=lane_allowed_paths,
            )
        )
        if not serviceable:
            wait_ctx = _record_unserviceable(
                conn=conn,
                session_id=session_id,
                chain_step=chain_step,
                project=project,
                item_id=str(item_id),
                expected_status=expected_status,
                live_status=current_status,
                expected_next_step=expected_next_step,
                live_next_step=live_next_step,
                release_claim=release_claim_on_unserviceable,
            )
            return FreshnessVerdict(
                outcome=FreshnessOutcome.UNSERVICEABLE,
                current_status=current_status,
                current_next_step=live_next_step,
                wait_context=wait_ctx)

        _emit_refresh_event(
            session_id=session_id,
            chain_step=chain_step,
            project=project,
            item_id=str(item_id),
            expected_status=expected_status,
            live_status=current_status,
            expected_next_step=expected_next_step,
            live_next_step=live_next_step,
        )
        refreshed = dict(scheduler_context or {})
        refreshed.update({
            "status": current_status,
            "next_step": live_next_step,
            "from_status": expected_status,
            "from_next_step": expected_next_step,
        })
        refreshed.setdefault("freshness_refreshed", True)
        return FreshnessVerdict(
            outcome=FreshnessOutcome.REWRITE,
            current_status=current_status,
            current_next_step=live_next_step,
            refreshed_context=refreshed)


__all__ = ["FreshnessOutcome", "FreshnessVerdict", "evaluate_freshness"]
