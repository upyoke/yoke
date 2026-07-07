"""Focused tests for the typed owner_kind helper."""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claim_owner import (
    OWNER_KIND_ITEM,
    OWNER_KIND_PROCESS,
    OWNER_KIND_SESSION,
    VALID_OWNER_KINDS,
    ContradictoryOwnerSignals,
    InvalidOwnerCombination,
    InvalidOwnerKind,
    Owner,
    classify_backfill,
    owner_columns_for_writer,
    owner_from_row,
    provenance_from_row,
    validate_owner,
)


class TestValidateOwner:
    def test_item_owner_requires_item_id(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(OWNER_KIND_ITEM)

    def test_item_owner_with_session_id_rejected(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(
                OWNER_KIND_ITEM, owner_item_id=1, owner_session_id="s",
            )

    def test_item_owner_with_work_claim_rejected(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(
                OWNER_KIND_ITEM, owner_item_id=1, owner_work_claim_id=5,
            )

    def test_item_owner_happy_path(self):
        owner = validate_owner(OWNER_KIND_ITEM, owner_item_id=42)
        assert owner == Owner(kind=OWNER_KIND_ITEM, item_id=42)

    def test_session_owner_requires_session_id(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(OWNER_KIND_SESSION)

    def test_session_owner_with_item_rejected(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(
                OWNER_KIND_SESSION, owner_session_id="s", owner_item_id=1,
            )

    def test_session_owner_happy_path(self):
        owner = validate_owner(OWNER_KIND_SESSION, owner_session_id="abc")
        assert owner == Owner(kind=OWNER_KIND_SESSION, session_id="abc")

    def test_process_owner_requires_work_claim_id(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(OWNER_KIND_PROCESS)

    def test_process_owner_with_session_rejected(self):
        with pytest.raises(InvalidOwnerCombination):
            validate_owner(
                OWNER_KIND_PROCESS, owner_work_claim_id=5,
                owner_session_id="s",
            )

    def test_process_owner_happy_path(self):
        owner = validate_owner(OWNER_KIND_PROCESS, owner_work_claim_id=5)
        assert owner == Owner(kind=OWNER_KIND_PROCESS, work_claim_id=5)

    def test_invalid_owner_kind_rejected(self):
        with pytest.raises(InvalidOwnerKind):
            validate_owner("orphan", owner_item_id=1)

    def test_empty_owner_kind_rejected(self):
        with pytest.raises(InvalidOwnerKind):
            validate_owner("")


class TestClassifyBackfill:
    def test_item_linked_classifies_as_item(self):
        owner = classify_backfill(
            item_id=42, work_claim_id=None, session_id="anything",
        )
        assert owner == Owner(kind=OWNER_KIND_ITEM, item_id=42)

    def test_work_claim_only_classifies_as_process(self):
        owner = classify_backfill(
            item_id=None, work_claim_id=7, session_id=None,
        )
        assert owner == Owner(kind=OWNER_KIND_PROCESS, work_claim_id=7)

    def test_session_only_classifies_as_session(self):
        owner = classify_backfill(
            item_id=None, work_claim_id=None, session_id="sess-abc",
        )
        assert owner == Owner(kind=OWNER_KIND_SESSION, session_id="sess-abc")

    def test_item_plus_work_claim_refused(self):
        with pytest.raises(ContradictoryOwnerSignals):
            classify_backfill(
                item_id=42, work_claim_id=7, session_id=None,
            )

    def test_nothing_refused(self):
        with pytest.raises(ContradictoryOwnerSignals):
            classify_backfill(
                item_id=None, work_claim_id=None, session_id=None,
            )

    def test_item_plus_session_classifies_as_item(self):
        # registering session does not override item ownership
        owner = classify_backfill(
            item_id=42, work_claim_id=None, session_id="registering",
        )
        assert owner.kind == OWNER_KIND_ITEM
        assert owner.item_id == 42

    def test_work_claim_plus_session_classifies_as_process(self):
        # registering session does not override process ownership
        owner = classify_backfill(
            item_id=None, work_claim_id=9, session_id="registering",
        )
        assert owner.kind == OWNER_KIND_PROCESS
        assert owner.work_claim_id == 9


class TestOwnerFromRow:
    def test_returns_none_when_owner_kind_missing(self):
        assert owner_from_row({"owner_kind": None}) is None

    def test_returns_none_when_key_absent(self):
        assert owner_from_row({}) is None

    def test_reads_item_owner(self):
        owner = owner_from_row({
            "owner_kind": OWNER_KIND_ITEM,
            "owner_item_id": 42,
            "owner_session_id": None,
            "owner_work_claim_id": None,
        })
        assert owner == Owner(kind=OWNER_KIND_ITEM, item_id=42)

    def test_reads_session_owner_ignoring_legacy_session_id(self):
        # The legacy session_id column is provenance — not the owner signal.
        owner = owner_from_row({
            "owner_kind": OWNER_KIND_SESSION,
            "owner_item_id": None,
            "owner_session_id": "owning-session",
            "owner_work_claim_id": None,
            "session_id": "registering-session",
        })
        assert owner == Owner(kind=OWNER_KIND_SESSION, session_id="owning-session")

    def test_reads_process_owner(self):
        owner = owner_from_row({
            "owner_kind": OWNER_KIND_PROCESS,
            "owner_item_id": None,
            "owner_session_id": None,
            "owner_work_claim_id": 7,
        })
        assert owner == Owner(kind=OWNER_KIND_PROCESS, work_claim_id=7)


class TestProvenanceFromRow:
    def test_prefers_registered_by_columns(self):
        prov = provenance_from_row({
            "registered_by_actor_id": 2,
            "registered_by_session_id": "live",
            "actor_id": 99,
            "session_id": "legacy",
        })
        assert prov.actor_id == 2
        assert prov.session_id == "live"

    def test_falls_back_to_legacy(self):
        prov = provenance_from_row({
            "registered_by_actor_id": None,
            "registered_by_session_id": None,
            "actor_id": 99,
            "session_id": "legacy",
        })
        assert prov.actor_id == 99
        assert prov.session_id == "legacy"

    def test_session_may_be_null(self):
        prov = provenance_from_row({
            "registered_by_actor_id": 3,
            "registered_by_session_id": None,
            "actor_id": 99,
            "session_id": None,
        })
        assert prov.actor_id == 3
        assert prov.session_id is None


class TestOwnerColumnsForWriter:
    def test_item_owner_columns(self):
        cols = owner_columns_for_writer(
            Owner(kind=OWNER_KIND_ITEM, item_id=42)
        )
        assert cols == {
            "owner_kind": OWNER_KIND_ITEM,
            "owner_item_id": 42,
            "owner_session_id": None,
            "owner_work_claim_id": None,
        }

    def test_session_owner_columns(self):
        cols = owner_columns_for_writer(
            Owner(kind=OWNER_KIND_SESSION, session_id="abc")
        )
        assert cols == {
            "owner_kind": OWNER_KIND_SESSION,
            "owner_item_id": None,
            "owner_session_id": "abc",
            "owner_work_claim_id": None,
        }

    def test_process_owner_columns(self):
        cols = owner_columns_for_writer(
            Owner(kind=OWNER_KIND_PROCESS, work_claim_id=7)
        )
        assert cols == {
            "owner_kind": OWNER_KIND_PROCESS,
            "owner_item_id": None,
            "owner_session_id": None,
            "owner_work_claim_id": 7,
        }


class TestValidOwnerKindsContract:
    def test_constants_exposed(self):
        assert VALID_OWNER_KINDS == (
            OWNER_KIND_ITEM, OWNER_KIND_SESSION, OWNER_KIND_PROCESS,
        )

    def test_kinds_are_lowercase_strings(self):
        for kind in VALID_OWNER_KINDS:
            assert isinstance(kind, str)
            assert kind == kind.lower()
