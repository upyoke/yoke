"""Readable presentation facts for stored event rows."""

from __future__ import annotations

import json
from typing import Any, Dict


def _context(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("envelope")
    try:
        envelope = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    context = envelope.get("context") if isinstance(envelope, dict) else None
    return context if isinstance(context, dict) else {}


def _event_category(row: Dict[str, Any]) -> str:
    token = " ".join(
        (
            str(row.get("event_kind") or ""),
            str(row.get("event_type") or ""),
            str(row.get("event_name") or ""),
        )
    ).lower()
    if "session" in token or "claim" in token:
        return "sessions"
    if any(word in token for word in ("deploy", "release", "delivery", "runstage")):
        return "delivery"
    if any(word in token for word in ("qa", "test", "evidence", "verdict")):
        return "qa"
    if any(word in token for word in ("strategy", "strategize", "drift")):
        return "strategy"
    if any(word in token for word in ("workflow", "item", "lifecycle", "status")):
        return "workflow"
    if any(word in token for word in ("auth", "sign", "permission", "access")):
        return "access"
    return "system"


def _context_label(context: Dict[str, Any], row: Dict[str, Any]) -> str:
    before = context.get("from_status") or context.get("from")
    after = context.get("to_status") or context.get("to")
    if before or after:
        return f"{before or '—'} → {after or '—'}"
    for keys in (
        ("stage", "result"),
        ("stage", "status"),
        ("function", "result"),
        ("action", "result"),
    ):
        values = [str(context.get(key) or "").strip() for key in keys]
        if any(values):
            return " · ".join(value for value in values if value)
    for key in ("title", "message", "reason", "function", "command"):
        value = str(context.get(key) or "").strip()
        if value:
            return value[:180]
    outcome = str(row.get("event_outcome") or "").strip()
    return outcome or str(row.get("event_type") or "")


def present_event(
    row: Dict[str, Any],
    item_facts: Dict[int, Dict[str, Any]],
    actor_labels: Dict[int, str],
) -> Dict[str, Any]:
    """Decorate a stored event with category, target, and source labels."""
    context = _context(row)
    item_text = str(row.get("item_id") or "")
    item_id = int(item_text) if item_text.isdigit() else None
    item = item_facts.get(item_id) if item_id is not None else None
    run_id = str(context.get("run_id") or context.get("workflow_run_id") or "").strip()
    session_id = str(row.get("session_id") or "").strip()
    if item:
        target_kind = "item"
        target_label = str(item["ref"])
        target_id = item_id
        target_project_id = item["project_id"]
    elif run_id:
        target_kind = "delivery"
        target_label = run_id
        target_id = run_id
        target_project_id = None
    elif session_id:
        target_kind = "session"
        target_label = session_id
        target_id = session_id
        target_project_id = None
    elif row.get("project"):
        target_kind = "project"
        target_label = str(row["project"])
        target_id = str(row["project"])
        target_project_id = None
    else:
        target_kind = "universe"
        target_label = "Universe"
        target_id = ""
        target_project_id = None

    actor_text = str(row.get("actor_id") or "")
    actor_id = int(actor_text) if actor_text.isdigit() else None
    source_label = (
        actor_labels.get(actor_id) if actor_id is not None else None
    ) or str(
        row.get("agent") or row.get("service") or row.get("source_type") or "system"
    )
    return {
        **row,
        "category": _event_category(row),
        "target_kind": target_kind,
        "target_label": target_label,
        "target_id": target_id,
        "target_project_id": target_project_id,
        "context_label": _context_label(context, row),
        "source_label": source_label,
    }


__all__ = ["present_event"]
