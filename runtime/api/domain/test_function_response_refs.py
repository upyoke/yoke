"""Server result projection uses actual project sequences, never id tails."""

import pytest

from yoke_core.domain.function_response_refs import collect_item_ids, public_result


def test_collects_nested_join_keys_without_resolving_other_records():
    result = {
        "id": 50,
        "rows": [{"item_id": 99, "qa_requirement_id": 40}],
        "item": {"id": 99, "public_ref": "APP-7"},
        "blocking_item_ids": [99, 100],
    }
    assert collect_item_ids(result) == {99, 100}
    public = public_result(result, {99: "APP-7", 100: "YOK-3"})
    assert public["id"] == 50
    assert public["rows"] == [{"public_ref": "APP-7", "qa_requirement_id": 40}]
    assert public["item"] == {"public_ref": "APP-7"}
    assert public["blocking_public_refs"] == ["APP-7", "YOK-3"]


def test_unresolved_key_never_becomes_fabricated_public_ref():
    assert "99" not in public_result({"item_id": 99}, {})["public_ref"]


def test_sparse_item_containers_render_their_internal_keys():
    source = {"items": [{"id": 99, "title": "example"}]}
    assert collect_item_ids(source) == {99}
    assert public_result(source, {99: "APP-7"}) == {
        "items": [{"public_ref": "APP-7", "title": "example"}]
    }


def test_other_records_with_public_item_refs_keep_their_primary_ids():
    qa = {"id": 11, "public_ref": "APP-7", "item_ref": "APP-7", "method_id": "command"}
    verdict = {"id": 22, "public_ref": "APP-7", "worker": "review"}
    source = {"rows": [qa, verdict], "item": {"id": 99, "public_ref": "APP-7"}}
    assert collect_item_ids(source) == {99}
    projected = public_result(source, {99: "APP-7"})
    assert projected["rows"] == [qa, verdict]
    assert projected["item"] == {"public_ref": "APP-7"}


@pytest.mark.parametrize(
    "field", ["candidate_containment_basis", "candidate_containment"]
)
def test_containment_protocol_does_not_become_public_item_rows(field):
    basis = {"projects": [{"items": [{"id": 99, "merge_sha": "a" * 40}]}]}
    result = {field: basis, "items": [{"id": 100}]}
    assert collect_item_ids(result) == {100}
    assert public_result(result, {100: "APP-7"}) == {
        field: basis,
        "items": [{"public_ref": "APP-7"}],
    }


def test_response_backstop_projects_nested_text_and_error_message(monkeypatch):
    from contextlib import nullcontext
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
    from yoke_core.domain import db_helpers, function_response_refs as projection

    refs = {3973: "PLAT-189", 99: "APP-7"}
    calls = []
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))

    def resolve(conn, ids):
        calls.append(set(ids))
        return refs

    monkeypatch.setattr(projection, "render_item_refs", resolve)
    response = FunctionCallResponse(
        function="example",
        version="v1",
        success=False,
        result={
            "rows": [{"message": "member 3973: requirement #40353 failed"}],
            "note": "deployment member 99 waits; item APP-7 stays public",
        },
        error=FunctionError(code="example", message="item 99 is blocked"),
    )
    public = projection.public_response(response)
    assert calls == [{3973, 99}]
    assert (
        public.result["rows"][0]["message"]
        == f"member {refs[3973]}: requirement #40353 failed"
    )
    assert (
        public.result["note"]
        == f"deployment member {refs[99]} waits; item APP-7 stays public"
    )
    assert public.error.message == f"item {refs[99]} is blocked"
    assert public.error.code == "example"


def test_response_backstop_hides_unresolved_names(monkeypatch):
    from contextlib import nullcontext
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
    from yoke_core.domain import db_helpers, function_response_refs as projection

    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(projection, "render_item_refs", lambda conn, ids: {})
    response = FunctionCallResponse(
        function="example",
        version="v1",
        success=False,
        error=FunctionError(code="missing", message="item 99 is missing"),
    )
    public = projection.public_response(response)
    assert "99" not in public.error.message
    assert "unresolved" in public.error.message
