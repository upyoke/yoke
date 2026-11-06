"""Validation and actions for non-gating operator questions."""

from __future__ import annotations

import re
from typing import Any, Mapping

from yoke_contracts.refusal_recovery import compose_refusal

KIND = "operator_question"
_SLUG = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")


def invalid(detail: str) -> ValueError:
    return ValueError(
        compose_refusal(
            f"operator_question_invalid: {detail}",
            recovery="Correct the question fields and retry decision-requests ask.",
        )
    )


def slug(value: Any) -> bool:
    return isinstance(value, str) and bool(_SLUG.fullmatch(value))


def _text(value: Any, field: str, limit: int, *, required: bool = False) -> None:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (required and not value.strip())
    ):
        raise invalid(
            f"{field} must contain {'1' if required else '0'} to {limit} characters"
        )


def validate(context: Mapping[str, Any]) -> None:
    _text(context.get("question"), "question", 2000, required=True)
    if "context" in context:
        _text(context["context"], "context", 8000)
    options = context.get("options", [])
    if not isinstance(options, list) or len(options) > 8:
        raise invalid("options must contain zero to eight entries")
    ids = set()
    for option in options:
        if not isinstance(option, dict) or not slug(option.get("id")):
            raise invalid("each option id must be a lowercase slug")
        if option["id"] == "freeform" or option["id"] in ids:
            raise invalid("option ids must be unique and cannot be freeform")
        ids.add(option["id"])
        _text(option.get("label"), "option label", 80, required=True)
        if "detail" in option:
            _text(option["detail"], "option detail", 500)
    recommended = context.get("recommended_option")
    if recommended is not None and (
        not isinstance(recommended, str) or recommended not in ids
    ):
        raise invalid("recommended_option must name an option id")
    freeform = context.get("allow_freeform", True)
    if not isinstance(freeform, bool) or (not options and not freeform):
        raise invalid("allow_freeform must be boolean and true without options")
    item_id = context.get("item_id")
    if item_id is not None and (type(item_id) is not int or item_id < 1):
        raise invalid("item_id must be a positive integer")


def actions(context: Mapping[str, Any]) -> list[str]:
    validate(context)
    return [option["id"] for option in context.get("options", [])] + (
        ["freeform"] if context.get("allow_freeform", True) else []
    )


def subject_ended(
    conn: Any, request: Mapping[str, Any], _observed_at: Any
) -> tuple[bool, str]:
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.workflow_runtime import (
        load_item_workflow_runtime,
        ENGINE_TERMINAL_STAGE_IDS,
    )

    context = request["subject_context"]
    item_id = context.get("item_id")
    if item_id is not None:
        row = conn.execute(
            f"SELECT status, workflow_id, workflow_version_id FROM items WHERE id={_p(conn)}",
            (item_id,),
        ).fetchone()
        if row is None:
            return True, "question item no longer exists"
        ended = row[0] in (
            load_item_workflow_runtime(conn, item_id).terminal_stage_ids
            | ENGINE_TERMINAL_STAGE_IDS
        )
        return ended, f"question item is {row[0]}"
    row = conn.execute(
        f"SELECT terminated_at FROM harness_sessions WHERE session_id={_p(conn)}",
        (request["requesting_session_id"],),
    ).fetchone()
    ended = row is None or row[0] is not None
    return (
        ended,
        "requesting session terminated or removed"
        if ended
        else "requesting session is not terminated",
    )
