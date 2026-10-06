"""Item identity at the dispatcher boundary: payload refs resolve inward.

Payload ``public_ref``-family keys resolve onto the ``item_id``-family keys
a handler's request model declares. Resolution is stubbed here — the
resolver's own semantics are proven against Postgres in
``test_item_ref_resolution``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.item_identity_keys import engine_key_for_wire
from yoke_core.domain.item_ref_resolution import ItemRefError
from yoke_core.domain.yoke_function_dispatch_payload_refs import (
    resolve_payload_public_refs,
)

REFS = {"YOK-5": 100, "YOK-6": 101, "EXT-5": 200}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: Optional[int] = None
    owner_item_id: Optional[int] = None
    epic_id: Optional[int] = None
    item_ids: Optional[List[int]] = None
    project: Optional[str] = None


class _OwnsRef(BaseModel):
    public_ref: Optional[str] = None
    item_id: Optional[int] = None


@contextmanager
def _conn(*_a, **_k):
    yield object()


def _fake_resolve(conn, token, *, project=None):
    if token in REFS:
        return REFS[token]
    if token == "5" and project == "ext":
        return 200
    raise ItemRefError("item_ref_needs_project", f"bad {token}")


def _request(payload: dict, project_id: Optional[str] = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="x.y",
        actor=ActorContext(actor_id=None, session_id="s"),
        target=TargetRef(kind="global", project_id=project_id),
        payload=payload,
    )


def _resolve(request: FunctionCallRequest, model=_Model, hint=None):
    with (
        patch("yoke_core.domain.db_helpers.connect", side_effect=_conn),
        patch(
            "yoke_core.domain.item_ref_resolution.resolve_item_ref",
            side_effect=_fake_resolve,
        ),
    ):
        return resolve_payload_public_refs(request, model, project_hint=hint)


def test_wire_keys_pair_onto_engine_keys():
    for engine, wire in (
        ("item_id", "public_ref"),
        ("owner_item_id", "owner_public_ref"),
        ("epic_id", "epic_public_ref"),
        ("item_ids", "public_refs"),
        ("member_item_ids", "member_public_refs"),
    ):
        assert engine_key_for_wire(wire) == engine
    assert engine_key_for_wire("project") is None


def test_payload_refs_resolve_onto_declared_engine_keys():
    request = _request(
        {
            "public_ref": "YOK-5",
            "owner_public_ref": "EXT-5",
            "public_refs": ["YOK-5", "YOK-6"],
        }
    )
    assert _resolve(request) is None
    assert request.payload == {
        "item_id": 100,
        "owner_item_id": 200,
        "item_ids": [100, 101],
    }


def test_epic_public_ref_resolves_onto_epic_id():
    request = _request({"epic_public_ref": "YOK-6"})
    assert _resolve(request) is None
    assert request.payload == {"epic_id": 101}


def test_bare_number_uses_explicit_project_only():
    request = _request({"public_ref": "5"}, project_id=None)
    refused = _resolve(request, hint="ext")
    assert refused is None and request.payload == {"item_id": 200}
    request = _request({"public_ref": "5"})
    refused = _resolve(request)
    assert refused is not None and refused.error.code == "public_ref_unresolved"
    assert refused.error.jsonpath == "$.payload.public_ref"


def test_payload_project_is_explicit_context():
    request = _request({"public_ref": "5", "project": "ext"})
    assert _resolve(request) is None
    assert request.payload["item_id"] == 200


def test_disagreeing_engine_key_is_refused_without_printing_ids():
    request = _request({"public_ref": "YOK-5", "item_id": 999})
    refused = _resolve(request)
    assert refused is not None
    assert "999" not in refused.error.message and "100" not in refused.error.message


def test_model_that_declares_the_ref_key_keeps_it():
    request = _request({"public_ref": "anything"})
    assert _resolve(request, model=_OwnsRef) is None
    assert request.payload == {"public_ref": "anything"}
