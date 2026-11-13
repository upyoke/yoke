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


def test_response_keeps_result_prose_and_projects_error_message(monkeypatch):
    from contextlib import nullcontext
    from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
    from yoke_core.domain import db_helpers, function_response_refs as projection

    refs = {99: "APP-7", 100: "YOK-3"}
    calls = []
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))

    def resolve(conn, ids):
        calls.append(set(ids))
        return refs

    monkeypatch.setattr(projection, "render_item_refs", resolve)
    prose = {
        "instructions": "Read prerequisites.md item 8 before the walk.",
        "rationale": ["item 4 and item 5 hold", "member 3973: requirement #40353"],
        "note": "item YOK-8 stays as written",
    }
    response = FunctionCallResponse(
        function="example",
        version="v1",
        success=False,
        result={**prose, "items": [{"item_id": 100}]},
        error=FunctionError(code="example", message="item 99 is blocked"),
    )
    public = projection.public_response(response)
    assert calls == [{99, 100}]
    assert {key: public.result[key] for key in prose} == prose
    assert public.result["items"][0]["public_ref"] == refs[100]
    assert "item_id" not in public.result["items"][0]
    assert public.error.message == f"item {refs[99]} is blocked"
    assert public.error.code == "example"


def test_result_prose_without_structured_ids_skips_lookup(monkeypatch):
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_core.domain import function_response_refs as projection

    def refuse(conn, ids):
        raise AssertionError("prose is not an item selector")

    monkeypatch.setattr(projection, "render_item_refs", refuse)
    result = {"body": "item YOK-8 and item 8 and epic 12 stay as written"}
    response = FunctionCallResponse(
        function="example", version="v1", success=True, result=result
    )
    assert projection.public_response(response).result == result


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


@pytest.mark.parametrize("function", ["packs.bundle.get", "packs.bundle.render"])
@pytest.mark.parametrize("version", ["1.1.5", "1.1.6", "1.1.7"])
def test_pack_response_preserves_content_addressed_application_source(
    monkeypatch, function, version
):
    from contextlib import nullcontext
    from pathlib import Path
    from types import SimpleNamespace

    from yoke_cli.packs.runner_support import _validate_bundle
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_core.domain import db_helpers, function_response_refs, pack_catalog

    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(
        pack_catalog, "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    calls = []
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))

    def resolve(conn, ids):
        calls.append(ids)
        return {number: f"APP-{number}" for number in ids}

    monkeypatch.setattr(function_response_refs, "render_item_refs", resolve)
    bundle = pack_catalog.build_pack_bundle(
        object(), project="sample", pack="webapp-scaffold", version=version,
        packs_dir=root / "packs",
        render_values={
            "api_port": "8000", "web_port": "3000", "project_slug": "sample",
            "project_name": "sample", "project_display_name": "Sample App",
            "project_description": "Sample application.",
        },
    )
    _validate_bundle(bundle)
    response = FunctionCallResponse(function=function, version="v1", success=True, result=bundle)
    public = function_response_refs.public_response(response)
    _validate_bundle(public.result)
    assert public.result == bundle
    assert not calls, "Literal examples in application source are not item selectors"
