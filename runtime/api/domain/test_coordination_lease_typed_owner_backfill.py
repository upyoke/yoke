"""Typed-owner backfill must skip rows live code already wrote."""

from __future__ import annotations

from importlib import import_module

_mod = import_module(
    "yoke_core.domain.migrations.0011_coordination_lease_typed_ownership"
)


def test_item_owner_is_already_typed() -> None:
    assert _mod._has_typed_owner({
        "owner_item_id": 12,
        "owner_session_id": None,
        "owner_work_claim_id": None,
    })


def test_session_owner_is_already_typed() -> None:
    assert _mod._has_typed_owner({
        "owner_item_id": None,
        "owner_session_id": "sess-1",
        "owner_work_claim_id": None,
    })


def test_process_owner_is_already_typed() -> None:
    assert _mod._has_typed_owner({
        "owner_item_id": None,
        "owner_session_id": None,
        "owner_work_claim_id": 99,
    })


def test_default_row_without_owner_column_is_not_typed() -> None:
    assert not _mod._has_typed_owner({
        "owner_item_id": None,
        "owner_session_id": None,
        "owner_work_claim_id": None,
    })
