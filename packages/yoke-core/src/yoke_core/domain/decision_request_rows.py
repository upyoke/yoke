"""Compose a page of requests, audience rules and recorded answers.

Each shared read runs once for the set; request_row is the one-element
form. Audience membership remains live and belongs to the audience resolver.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from yoke_core.domain import audiences, db_backend
from yoke_core.domain.approval_policy import DEFAULT_APPROVAL_MODE
from yoke_core.domain.decision_request_contract import (
    DECISION_KINDS,
    RETIRED_DECISION_KINDS,
)
from yoke_core.domain.decision_request_operator_question import (
    actions as question_actions,
)
from yoke_core.domain.decision_answers import decisions_for_requests
from yoke_core.domain.decision_request_live_evidence import (
    live_evidence,
    settled_evidence_state,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def request_rows(conn: Any, request_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Compose each named request, keyed by id; unknown ids are absent.

    Live evidence stays per request because it is a question about that
    request's own subject rather than one the page shares.
    """
    ids = tuple(dict.fromkeys(int(value) for value in request_ids))
    if not ids:
        return {}
    from yoke_core.domain.approval_decisions import evaluate_decisions

    placeholders = ", ".join(_p(conn) for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM decision_requests WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    audience_rules = audiences.rules_for_audiences(
        conn, (int(row["audience_id"]) for row in rows)
    )
    answers = decisions_for_requests(conn, ids)
    composed: dict[int, dict[str, Any]] = {}
    for raw in rows:
        result = dict(raw)
        request_id = int(result["id"])
        try:
            result["subject_context"] = json.loads(result["subject_context"] or "{}")
        except (TypeError, json.JSONDecodeError):
            result["subject_context"] = {}
        if result["status"] == "pending":
            live = live_evidence(
                conn,
                result["kind"],
                result["subject_context"],
                subject_key=result["subject_key"],
                project_id=result.get("project_id"),
            )
            if live is not None:
                result["subject_context"].update(live)
        elif result["status"] == "resolved":
            settled = settled_evidence_state(
                conn,
                result["kind"],
                result["subject_context"],
                subject_key=result["subject_key"],
                project_id=result.get("project_id"),
            )
            if settled is not None:
                result["subject_context"]["evidence"] = {
                    **result["subject_context"]["evidence"],
                    "state": settled,
                }
        if result["kind"] == "operator_question":
            from yoke_core.domain.decision_request_question_filing import (
                describe_question,
            )

            describe_question(conn, result)
        result["actions"] = (
            []
            if result["kind"] in RETIRED_DECISION_KINDS
            else question_actions(result["subject_context"])
            if result["kind"] == "operator_question"
            else list(DECISION_KINDS[result["kind"]].actions)
        )
        rules = audience_rules.get(int(result["audience_id"]), [])
        result["audience_rules"] = rules
        # Gate policy consumes rule boxes, while membership has one shared owner.
        result["role_authorities"] = [
            {
                "scope_kind": rule["scope_kind"],
                "scope_id": rule["scope_id"],
                "role_name": rule["role_name"],
            }
            for rule in rules
            if rule["scope_kind"] != "actor"
        ]
        result["named_actor_ids"] = [
            int(rule["scope_id"]) for rule in rules if rule["scope_kind"] == "actor"
        ]
        result["approval_mode"] = str(
            result.get("approval_mode") or DEFAULT_APPROVAL_MODE
        )
        result["decisions"] = answers.get(request_id, [])
        result["approval_progress"] = evaluate_decisions(
            conn,
            result,
            decisions=result["decisions"],
        ).as_dict()
        composed[request_id] = result
    return composed


def request_row(conn: Any, request_id: int) -> dict[str, Any]:
    """Compose one request, the one-element case of :func:`request_rows`."""
    composed = request_rows(conn, (int(request_id),)).get(int(request_id))
    if composed is None:
        raise LookupError(f"decision request {request_id} does not exist")
    return composed


__all__ = ["request_row", "request_rows"]
