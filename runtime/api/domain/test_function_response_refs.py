"""Server result projection uses actual project sequences, never id tails."""

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
