"""Item identity at the dispatcher boundary: payload refs in, refs out.

Payload ``public_ref``-family keys resolve onto the ``item_id``-family keys
a handler's request model declares; responses gain the public ref beside
every engine id. Resolution and rendering are stubbed here — the resolver's
own semantics are proven against Postgres in ``test_item_ref_resolution``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import List, Optional
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.item_identity_keys import engine_key_for_wire, wire_key_for_engine
from yoke_core.domain.item_identity_projection import (
    apply_public_refs,
    collect_item_ids,
)
from yoke_core.domain.item_ref_resolution import ItemRefError
from yoke_core.domain.yoke_function_dispatch_payload_refs import (
    resolve_payload_public_refs,
)
from yoke_core.domain.yoke_function_dispatch_projection import (
    project_response_item_identity,
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


def test_key_pairing_is_symmetric():
    for engine, wire in (
        ("item_id", "public_ref"),
        ("owner_item_id", "owner_public_ref"),
        ("epic_id", "epic_public_ref"),
        ("item_ids", "public_refs"),
        ("member_item_ids", "member_public_refs"),
    ):
        assert wire_key_for_engine(engine) == wire
        assert engine_key_for_wire(wire) == engine
    assert wire_key_for_engine("claim_id") is None
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


def test_projection_fills_wire_refs_beside_engine_ids():
    result = {
        "item_id": 100,
        "rows": [{"owner_item_id": "200", "epic_id": 101}],
        "item_ids": [100, 101],
        "frontier": {"item_id": "YOK-5"},
        "kept": {"item_id": 100, "public_ref": "already"},
        "claim_id": 7,
    }
    assert sorted(set(collect_item_ids(result))) == [100, 101, 200]
    out = apply_public_refs(result, {100: "YOK-5", 101: "YOK-6", 200: "EXT-5"})
    assert out["public_ref"] == "YOK-5"
    assert out["rows"][0]["owner_public_ref"] == "EXT-5"
    assert out["rows"][0]["epic_public_ref"] == "YOK-6"
    assert out["public_refs"] == ["YOK-5", "YOK-6"]
    assert "public_ref" not in out["frontier"]
    assert out["kept"]["public_ref"] == "already"
    assert out["item_id"] == 100


def test_response_projection_degrades_to_a_warning():
    response = FunctionCallResponse(
        success=True,
        function="x.y",
        version="v1",
        result={"item_id": 100},
    )

    @contextmanager
    def _broken(*_a, **_k):
        raise RuntimeError("no database")
        yield

    with patch("yoke_core.domain.db_helpers.connect", side_effect=_broken):
        projected = project_response_item_identity(response)
    assert projected.result == {"item_id": 100}
    assert projected.warnings[-1].code == "public_ref_projection_failed"
