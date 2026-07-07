"""Frozen-attestation immutability tests for ``yoke_core.domain.backlog``.

Shared fixtures and seed helpers are imported from ``test_backlog``. General
structured-write tests live in ``test_backlog_queries_structured.py``.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from yoke_core.domain import backlog, db_backend
from runtime.api.test_backlog import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestExecuteStructuredWriteFreezeImmutability:
    """Write-path integration coverage for AC-15 / AC-68.

    Seeds an item with a frozen attestation, then confirms
    ``execute_structured_write`` rejects attempts to rename the profile's
    ``model_name`` or mutate authored attestation fields. The lock clears
    only through the joint gate re-entry at ``refining-idea`` (not
    exercised here).
    """

    _FROZEN_ATTESTATION_JSON = (
        '{"frozen_at":"2026-04-22T17:52:49Z",'
        '"invariants":["items.status canonical lifecycle"],'
        '"pre_merge_readers_writers":[{"path":"p","role":"reader"}],'
        '"rehearsal_commands":["python3 -m pytest runtime/api/"],'
        '"residual_risk_notes":"Dashboard one-cycle lag."}'
    )

    _PRIMARY_PROFILE_JSON = (
        '{"state":"declared","model_name":"primary","mutation_intent":"apply",'
        '"migration_modules":["add_col"],"compatibility_class":"pre_merge_safe",'
        '"migration_strategy":"additive_only",'
        '"schema_kinds":["additive"],"data_kinds":[],'
        '"affected_surfaces":[],"count_preserving":true}'
    )

    _SECONDARY_PROFILE_JSON = (
        '{"state":"declared","model_name":"secondary","mutation_intent":"apply",'
        '"migration_modules":["add_col"],"compatibility_class":"pre_merge_safe",'
        '"migration_strategy":"additive_only",'
        '"schema_kinds":["additive"],"data_kinds":[],'
        '"affected_surfaces":[],"count_preserving":true}'
    )

    def _seed_frozen_item(self, tmp_db):
        _seed_item(tmp_db, id=10)
        conn = _conn(tmp_db)
        p = _p(conn)
        conn.execute(
            f"UPDATE items SET db_mutation_profile = {p}, db_compatibility_attestation = {p} WHERE id = 10",
            (self._PRIMARY_PROFILE_JSON, self._FROZEN_ATTESTATION_JSON),
        )
        conn.commit()
        conn.close()

    def test_rejects_model_name_rename_under_freeze(self, tmp_db):
        self._seed_frozen_item(tmp_db)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_mutation_profile",
                content=self._SECONDARY_PROFILE_JSON,
                out=out,
            )
        assert result["success"] is False
        assert "model_name" in result["error"]
        assert "refining-idea" in result["error"]
        # Confirm the stored profile was not modified
        assert _item_field(tmp_db, 10, "db_mutation_profile") == self._PRIMARY_PROFILE_JSON

    def test_allows_profile_rewrite_with_same_model_name(self, tmp_db):
        self._seed_frozen_item(tmp_db)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_mutation_profile",
                content=self._PRIMARY_PROFILE_JSON,
                out=out,
            )
        assert result["success"] is True

    def test_rejects_authored_attestation_change_under_freeze(self, tmp_db):
        self._seed_frozen_item(tmp_db)
        tampered = (
            '{"frozen_at":"2026-04-22T17:52:49Z",'
            '"invariants":["tampered invariant"],'
            '"pre_merge_readers_writers":[{"path":"p","role":"reader"}],'
            '"rehearsal_commands":["python3 -m pytest runtime/api/"],'
            '"residual_risk_notes":"Dashboard one-cycle lag."}'
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_compatibility_attestation",
                content=tampered,
                out=out,
            )
        assert result["success"] is False
        assert "invariants" in result["error"]
        assert "refining-idea" in result["error"]
        # Stored attestation unchanged
        assert _item_field(tmp_db, 10, "db_compatibility_attestation") == self._FROZEN_ATTESTATION_JSON

    def test_profile_write_advances_spec_updated_at_and_by(self, tmp_db):
        # db_mutation_profile writes advance spec_updated_at and
        # record spec_updated_by — these are content-tracking fields.
        _seed_item(tmp_db, id=10)
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_mutation_profile",
                content=self._PRIMARY_PROFILE_JSON,
                source="engineer",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "spec_updated_by") == "engineer"
        assert _item_field(tmp_db, 10, "spec_updated_at")

    def test_attestation_write_advances_spec_updated_at_and_by(self, tmp_db):
        # db_compatibility_attestation writes also advance
        # spec_updated_at and record spec_updated_by.
        _seed_item(tmp_db, id=10)
        # Use an unfrozen attestation so check_authored_fields_frozen passes.
        attestation = (
            '{"invariants":["initial"],'
            '"rehearsal_commands":["python3 -m pytest"],'
            '"residual_risk_notes":"n/a",'
            '"pre_merge_readers_writers":[{"path":"p","role":"reader"}]}'
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_compatibility_attestation",
                content=attestation,
                source="engineer",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "spec_updated_by") == "engineer"
        assert _item_field(tmp_db, 10, "spec_updated_at")

    def test_rejects_clearing_frozen_at_under_freeze(self, tmp_db):
        self._seed_frozen_item(tmp_db)
        cleared = (
            '{"frozen_at":null,'
            '"invariants":["items.status canonical lifecycle"],'
            '"pre_merge_readers_writers":[{"path":"p","role":"reader"}],'
            '"rehearsal_commands":["python3 -m pytest runtime/api/"],'
            '"residual_risk_notes":"Dashboard one-cycle lag."}'
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_structured_write(
                item_id=10,
                field="db_compatibility_attestation",
                content=cleared,
                out=out,
            )
        assert result["success"] is False
        assert "frozen_at" in result["error"]
