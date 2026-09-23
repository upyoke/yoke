"""Common cells for active/recent board session tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from yoke_contracts.board.board_db import BoardDBLike
from yoke_contracts.board.sections_sessions_scope import session_project_label
from yoke_contracts.executor_labels import EXECUTOR_EMOJI
from yoke_contracts.model_reference_catalog import validate_catalog
from yoke_contracts.session_model_facts import REQUESTED_LABEL
from yoke_contracts.session_usage_display import usage_cell
from yoke_contracts.session_usage_facts import usage_from_document
from yoke_contracts.session_usage_pricing import estimated_session_cost


def _resolve_executor_emoji(executor: str) -> str:
    """Resolve the emoji for an executor with family-prefix fallback."""
    if not executor:
        return ""
    if executor in EXECUTOR_EMOJI:
        return EXECUTOR_EMOJI[executor]
    if executor.startswith("claude-"):
        return EXECUTOR_EMOJI.get("claude-code", "")
    if executor.startswith("codex-"):
        return EXECUTOR_EMOJI.get("codex", "")
    return ""


def _display_model(model: Optional[str], requested_model: Optional[str]) -> str:
    """Render what served this session, or the ask, labelled as an ask.

    An unattested session shows what it requested rather than nothing, but
    never silently: the label is what keeps a request out of the column an
    operator reads as "what ran".
    """
    served = (model or "").strip()
    if served:
        return served
    requested = (requested_model or "").strip()
    return f"{requested}{REQUESTED_LABEL}" if requested else "?"


def _display_session_id(session_id: Optional[str]) -> str:
    """Render the session id whole; an elided one names several sessions."""
    return session_id or "?"


def _render_executor(executor: str, executor_surface: Optional[str]) -> str:
    display_value = executor_surface or executor
    exec_emoji = _resolve_executor_emoji(display_value or "")
    return f"{exec_emoji} {display_value}" if exec_emoji else (display_value or "?")


def _display_usage(
    db: BoardDBLike, usage_totals: Optional[str], offered_at: str
) -> str:
    """Render what this session consumed beside what it would have cost.

    The dollar half is an API-equivalent estimate priced at read time from
    the revision effective when this session was first registered.
    """
    when = datetime.fromisoformat(offered_at.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("session offered_at must be a UTC timestamp")
    stamp = (
        when.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    sql = (
        "SELECT revision_id,effective_at,catalog_json "
        "FROM model_reference_revisions WHERE effective_at <= %s "
        "ORDER BY effective_at DESC,published_at DESC,revision_id DESC LIMIT 1"
    )
    params = (stamp,)
    usage = usage_from_document(usage_totals)
    has_query = getattr(db, "has_query", None)
    if callable(has_query) and not has_query(sql, params):
        return usage_cell(usage, None)
    rows = db.query(sql, params)
    if not rows:
        raise ValueError("no model catalog revision covers this session; publish one")
    revision_id, effective_at, document = rows[0]
    revision = {
        "revision_id": revision_id,
        "effective_at": effective_at,
        "records": validate_catalog(json.loads(document)),
    }
    return usage_cell(usage, estimated_session_cost(usage, revision))


def session_common_cells(
    db: BoardDBLike,
    sid: str,
    executor: str,
    executor_surface: Optional[str],
    model: Optional[str],
    requested_model: Optional[str],
    usage_totals: Optional[str],
    offered_at: str,
    project_id: object,
) -> list[str]:
    return [
        f"`{_display_session_id(sid)}`",
        session_project_label(db, project_id),
        _render_executor(executor, executor_surface),
        _display_model(model, requested_model),
        _display_usage(db, usage_totals, offered_at),
    ]
