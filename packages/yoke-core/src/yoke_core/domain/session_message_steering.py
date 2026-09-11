"""Resolving a role-addressed Fleet message to the seat that should get it.

``yoke say --steering`` carries no address. The server derives one from the
work the SENDER holds: the item's project is the scope the message is
addressed within, and the item -- with the strategy document it is linked
to -- is what a narrowed seat keys on. Whether a session receives it is then decided at
DELIVERY time by :mod:`yoke_core.domain.steering_scope_coverage`, not at
send time, so a message written while one seat was live is still correct
after that seat ends.

The work a sender holds includes the work it just finished: close-out
releases the item claim before the DONE report is written. Ordinary
``--steering`` mail still uses :mod:`yoke_core.domain.session_item_scope`.
A DONE heading names PREFIX-N; that item, once it matches a claim this
session holds or released, is the address so a live claim on another
project cannot steal the completion.

An itemless sender -- a dashboard, an operator shell, a seat writing to a
peer scope -- has never held work to derive an address from and supplies
the scope explicitly instead. Both forms produce the same pair: the scope
the message belongs to, and the sender's item when there is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_contracts.session_control.recipient_selector import (
    STEERING_SCOPE_PROJECT_KEY,
    RecipientSelector,
)
from yoke_core.domain.session_item_scope import SessionItemScope, session_item_scope
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.steering_scope_membership import item_document_link
from yoke_core.domain.work_claim_scope_shape import STEERING_DOCUMENT_KEY


ADDRESS_UNRESOLVED_CODE = "steering_address_unresolved"


@dataclass(frozen=True)
class SteeringAddress:
    """What a role-addressed send resolved to before any seat is consulted."""

    scope: dict[str, Any]
    sender_item_id: Optional[int]
    sender_document: Optional[str] = None
    sender_document_project_id: Optional[int] = None

    @property
    def project_id(self) -> int:
        return int(self.scope[STEERING_SCOPE_PROJECT_KEY])

    def coverage_target(self) -> dict[str, Any]:
        """The addressed work, as the coverage rule reads it."""
        from yoke_core.domain.steering_scope_coverage import DOCUMENT_PROJECT_KEY

        target = dict(self.scope)
        if self.sender_item_id is not None:
            target["item_id"] = int(self.sender_item_id)
        if self.sender_document is not None:
            target[STEERING_DOCUMENT_KEY] = self.sender_document
        if self.sender_document_project_id is not None:
            target[DOCUMENT_PROJECT_KEY] = int(self.sender_document_project_id)
        return target


def resolve_steering_address(
    conn: Any,
    selector: RecipientSelector,
    *,
    sender_session_id: str | None,
    reported_item: SessionItemScope | None = None,
) -> SteeringAddress:
    """Derive the scope and item a ``--steering`` send is addressed within."""
    if reported_item is not None:
        document = _document_for(conn, reported_item.item_id)
        return SteeringAddress(
            scope={STEERING_SCOPE_PROJECT_KEY: reported_item.project_id},
            sender_item_id=reported_item.item_id,
            sender_document=None if document is None else document[1],
            sender_document_project_id=None if document is None else document[0],
        )
    if selector.steering_scope is not None:
        scope = dict(selector.steering_scope)
        try:
            scope[STEERING_SCOPE_PROJECT_KEY] = int(scope[STEERING_SCOPE_PROJECT_KEY])
        except (TypeError, ValueError) as exc:
            raise SessionMessageError(
                "selector_invalid",
                f"steering scope {STEERING_SCOPE_PROJECT_KEY!r} must be a project id",
                jsonpath="$.payload.selector.steering_scope",
            ) from exc
        held = session_item_scope(conn, sender_session_id)
        item_id = (
            held.item_id
            if held is not None and held.project_id == scope[STEERING_SCOPE_PROJECT_KEY]
            else None
        )
        document = _document_for(conn, item_id)
        return SteeringAddress(
            scope=scope,
            sender_item_id=item_id,
            sender_document=None if document is None else document[1],
            sender_document_project_id=None if document is None else document[0],
        )
    held = session_item_scope(conn, sender_session_id)
    if held is None:
        raise SessionMessageError(
            ADDRESS_UNRESOLVED_CODE,
            "--steering addresses the seat covering the work you hold or "
            "most recently held, and this session has held no item work "
            "claim to derive that from. Acquire the item claim first, or "
            "name the scope explicitly with "
            "--steering-scope '{\"project_id\": N}'.",
            jsonpath="$.payload.selector.steering",
        )
    document = _document_for(conn, held.item_id)
    return SteeringAddress(
        scope={STEERING_SCOPE_PROJECT_KEY: held.project_id},
        sender_item_id=held.item_id,
        sender_document=None if document is None else document[1],
        sender_document_project_id=None if document is None else document[0],
    )


def _document_for(
    conn: Any, item_id: Optional[int]
) -> Optional[tuple[int, str]]:
    """Owning project plus slug of the addressed item's document, if any."""
    return None if item_id is None else item_document_link(conn, int(item_id))


def seat_session_id(
    conn: Any, address: SteeringAddress
) -> tuple[str | None, Mapping[str, Any] | None]:
    """The live seat covering this address, or ``(None, None)`` to park."""
    from yoke_core.domain.steering_scope_coverage import covering_seat

    seat = covering_seat(conn, address.coverage_target())
    if seat is None:
        return None, None
    return str(seat["session_id"]), seat


__all__ = [
    "ADDRESS_UNRESOLVED_CODE",
    "SteeringAddress",
    "resolve_steering_address",
    "seat_session_id",
]
