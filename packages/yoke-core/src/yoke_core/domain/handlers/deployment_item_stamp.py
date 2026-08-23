"""Internal server-side member-item stamps for deployment runs.

The deployment pipeline runs as a machine process with no work claim on
the member items, so ``items.scalar.update``'s claim gate refuses its
stamps. The pipeline used to route around that through a legacy
subprocess router whose bare-digit item argument is parsed as a
public sequence under the default project — a stamp that lands on no
row, or on the wrong one, while the caller prints success.

This handler is the sanctioned write those stamps go through instead:
one function per member-item scalar, addressed by an integer
``target.item_id`` the server resolves before any permission check,
writing through the same multi-field updater every other item write
uses, then reading the row back before commit so the response can
state whether the value actually landed. The pipeline refuses its
stage loudly when this returns anything but success — a stamp that
did not land can never look like one that did.

It is ``adapter_status='internal'`` (deploy-run glue, never an agent
CLI surface), ``claim_required_kind=None`` because the pipeline holds
no session claim by construction, and ``ambient_session_required=False``
because a deploy runner may resolve no harness session. The PROJECT +
items-write authorization scope gates the write; see
``function_authz_product_scopes``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


#: The only scalars a deployment run may stamp on a member item. Both are
#: freeform strings owned by the deploy/done path; nothing else crosses here.
STAMPABLE_FIELDS = ("deploy_stage", "deployed_to")


class DeploymentItemStampRequest(BaseModel):
    field: str
    value: str


class DeploymentItemStampResponse(BaseModel):
    item_id: int
    field: str
    value: str
    verified: bool
    previous_value: str = ""


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def handle_deployment_item_stamp(request: FunctionCallRequest) -> HandlerOutcome:
    """Stamp one member-item scalar and verify the row read back.

    The update runs through :func:`backlog_item_db_writes._update_item_multi`
    (the shared writer, which also maintains ``updated_at``) with
    ``commit=False`` so a failed read-back rolls the transaction back
    instead of reporting a write that silently matched nothing.
    """
    item_id = _require_item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "deployment_item_stamp requires target.item_id",
        )
    try:
        body = DeploymentItemStampRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err(
            "payload_invalid",
            f"deployment_item_stamp payload invalid: {exc}",
        )
    if body.field not in STAMPABLE_FIELDS:
        return _err(
            "field_not_stampable",
            f"field {body.field!r} is not a deployment stamp surface; "
            f"stampable fields: {', '.join(STAMPABLE_FIELDS)}",
        )

    from yoke_core.domain.backlog_item_db_writes import _update_item_multi

    try:
        with _connect_rw() as conn:
            p = _placeholder(conn)
            prior_row = conn.execute(
                f"SELECT {body.field} FROM items WHERE id = {p}",
                (item_id,),
            ).fetchone()
            if prior_row is None:
                conn.rollback()
                return _err(
                    "item_not_found",
                    f"no items row with id={item_id}; stamp not applied",
                )
            previous = "" if prior_row[0] is None else str(prior_row[0])
            _update_item_multi(
                conn, item_id, {body.field: body.value}, commit=False,
            )
            verify_row = conn.execute(
                f"SELECT {body.field} FROM items WHERE id = {p}",
                (item_id,),
            ).fetchone()
            landed = (
                verify_row is not None
                and verify_row[0] is not None
                and str(verify_row[0]) == body.value
            )
            if not landed:
                conn.rollback()
                return _err(
                    "stamp_verification_failed",
                    f"items.id={item_id}: {body.field} did not read back as "
                    f"{body.value!r}; transaction rolled back",
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced so the stage refuses
        return _err("deployment_item_stamp_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "field": body.field,
            "value": body.value,
            "verified": True,
            "previous_value": previous,
        },
        primary_success=True,
    )


__all__ = [
    "DeploymentItemStampRequest",
    "DeploymentItemStampResponse",
    "STAMPABLE_FIELDS",
    "handle_deployment_item_stamp",
]
