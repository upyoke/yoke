"""Print-layer translation from internal item ids to public refs."""

from __future__ import annotations

from pydantic import ValidationError

from yoke_cli.transport.public_ref_display import (
    apply_public_refs,
    coerce_internal_item_id,
    collect_internal_item_ids,
)
from yoke_contracts.api.function_call import TargetRef


def test_collect_walks_nested_id_keys() -> None:
    ids = collect_internal_item_ids(
        {
            "item_id": 11,
            "nested": {"current_item_id": "12", "epic_id": 13},
            "rows": [{"recent_item_id": 11}, {"item_id": 14}],
        }
    )
    assert ids == [11, 12, 13, 14]


def test_apply_replaces_ids_with_public_ref_keys() -> None:
    display = apply_public_refs(
        {
            "item_id": 11,
            "current_item_id": 12,
            "scope": {"item_id": 11},
            "internal_id": 11,
        },
        {11: "YOK-11", 12: "YOK-12"},
    )
    assert display == {
        "public_ref": "YOK-11",
        "current_public_ref": "YOK-12",
        "scope": {"public_ref": "YOK-11"},
    }


def test_apply_omits_untranslated_ids() -> None:
    display = apply_public_refs({"item_id": 99, "title": "x"}, {})
    assert display == {"title": "x"}


def test_apply_does_not_pair_existing_public_ref() -> None:
    display = apply_public_refs(
        {"item_id": 11, "public_ref": "YOK-11", "title": "x"},
        {11: "YOK-11"},
    )
    assert display == {"public_ref": "YOK-11", "title": "x"}


def test_coerce_rejects_bool_and_zero() -> None:
    assert coerce_internal_item_id(True) is None
    assert coerce_internal_item_id(0) is None
    assert coerce_internal_item_id("11") == 11


def test_target_ref_rejects_retired_key() -> None:
    try:
        TargetRef.model_validate({"kind": "item", "item_ref": "YOK-1"})
    except ValidationError as exc:
        assert "public_ref" in str(exc)
        return
    raise AssertionError("retired target key must fail validation")
