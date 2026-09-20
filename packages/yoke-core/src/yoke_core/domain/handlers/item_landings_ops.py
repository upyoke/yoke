"""Registered append and read for an item's landing history.

The merge boundary runs on the machine holding the checkout, and a control
plane reached over https has no local database there, so the append crosses
that boundary as a registered call exactly as the merge receipt does.

``item_landings.record`` is claim-free merge glue for the same reason the
done-transition finalize writes are: the item claim and the merge lock are
enforced upstream by the merge boundary, and a landing record that could be
refused here would take the audit trail down with the merge it describes.
``item_landings.list`` is an ordinary read — the item page and the operator
CLI both ask it who landed what, and when.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend
from yoke_core.domain.item_landings import (
    ItemLanding,
    append_landing,
    landings_for_item,
)
from yoke_core.domain.item_landings_delivery import delivery_by_landing
from yoke_core.domain.item_landings_schema import LANDING_ROUTES
from yoke_core.domain.session_message_types import row_dict
from yoke_contracts.public_ref import ITEM_NOT_FOUND


class RecordItemLandingRequest(BaseModel):
    merge_sha: str = Field(..., min_length=1)
    route: str = Field(..., min_length=1)
    landed_at: str = Field(..., min_length=1)
    candidate_sha: str = ""
    pr_number: str = ""
    target_branch: str = ""


class RecordItemLandingResponse(BaseModel):
    item_id: int
    merge_sha: str
    #: False when this landing was already recorded — a re-entered close-out
    #: converging, not a failure.
    appended: bool


class ListItemLandingsRequest(BaseModel):
    pass


class ListItemLandingsResponse(BaseModel):
    item_id: int
    rows: List[dict]
    count: int
    #: True when the landings are readable but which release carried them is
    #: not. Each row's ``delivery`` is then absent because the question could
    #: not be asked, which is a different answer from "nothing delivered it".
    delivery_unreadable: bool = False


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.kind != "item" or request.target.item_id is None:
        return None
    return int(request.target.item_id)


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def handle_record_item_landing(request: FunctionCallRequest) -> HandlerOutcome:
    """Append one landing to this item's history."""
    item_id = _item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "item_landings.record requires target.kind='item' and item_id",
        )
    try:
        body = RecordItemLandingRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _err("payload_invalid", f"landing payload invalid: {exc}")
    if body.route not in LANDING_ROUTES:
        return _err(
            "payload_invalid",
            f"landing route {body.route!r} is not one of "
            f"{', '.join(LANDING_ROUTES)}",
        )
    try:
        with _connect_rw() as conn:
            appended = append_landing(
                conn,
                ItemLanding(
                    item_id=item_id,
                    merge_sha=body.merge_sha,
                    candidate_sha=body.candidate_sha,
                    pr_number=body.pr_number,
                    target_branch=body.target_branch,
                    route=body.route,
                    landed_at=body.landed_at,
                ),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced as an advisory refusal
        return _err("item_landing_record_failed", str(exc))
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "merge_sha": body.merge_sha,
            "appended": appended,
        },
        primary_success=True,
    )


def _item_delivery_scope(conn: Any, item_id: int) -> Optional[tuple[int, str, Any]]:
    """This item's project, selected flow, and that flow's environment."""
    p = _p(conn)
    row = conn.execute(
        "SELECT project_id, COALESCE(deployment_flow, '') AS deployment_flow "
        f"FROM items WHERE id={p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    value = row_dict(row)
    flow = str(value.get("deployment_flow") or "").strip()
    environment_id: Any = None
    if flow:
        flow_row = conn.execute(
            f"SELECT target_environment_id FROM deployment_flows WHERE id={p}",
            (flow,),
        ).fetchone()
        if flow_row is not None:
            environment_id = row_dict(flow_row).get("target_environment_id")
    return int(value["project_id"]), flow, environment_id


def handle_list_item_landings(request: FunctionCallRequest) -> HandlerOutcome:
    """Every landing this item made, oldest first, each with its release."""
    item_id = _item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "item_landings.list requires target.kind='item' and item_id",
        )
    try:
        ListItemLandingsRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _err("payload_invalid", f"landing query invalid: {exc}")
    try:
        with _connect_rw() as conn:
            scope = _item_delivery_scope(conn, item_id)
            if scope is None:
                return _err("target_not_found", ITEM_NOT_FOUND)
            project_id, flow, environment_id = scope
            landings = landings_for_item(conn, item_id)
            # The landings are the audit record and answer on their own. Which
            # release carried them is a second question over repository and
            # release state that can fail by itself, and losing the record to
            # that would be the wrong trade -- but so would reporting an
            # unasked question as "nothing delivered it".
            try:
                delivered = delivery_by_landing(
                    conn,
                    merge_shas=[landing.merge_sha for landing in landings],
                    project_id=project_id,
                    environment_id=environment_id,
                    flow=flow,
                )
                unreadable = False
            except Exception:  # noqa: BLE001 - degraded to an unknown answer
                delivered, unreadable = {}, True
    except Exception as exc:  # noqa: BLE001 - surfaced as an advisory refusal
        return _err("item_landings_read_failed", str(exc))
    rows = []
    for landing in landings:
        payload = landing.payload()
        if not unreadable:
            payload["delivery"] = delivered.get(landing.merge_sha)
        rows.append(payload)
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "rows": rows,
            "count": len(rows),
            "delivery_unreadable": unreadable,
        },
        primary_success=True,
    )


__all__ = [
    "ListItemLandingsRequest",
    "ListItemLandingsResponse",
    "RecordItemLandingRequest",
    "RecordItemLandingResponse",
    "handle_list_item_landings",
    "handle_record_item_landing",
]
