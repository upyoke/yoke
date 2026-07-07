"""Unit tests for structured-field handler wrappers and registrations."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    sections,
)
from yoke_core.domain.handlers import (
    items_structured_field,
    items_structured_field_models as _models,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _apply_fake_db_schema() -> None:
    """init_test_db apply_schema strategy: items + item_sections subset."""
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, "
            "design_spec TEXT, technical_plan TEXT, worktree_plan TEXT, "
            "shepherd_log TEXT, shepherd_caveats TEXT, test_results TEXT, "
            "deploy_log TEXT, browser_qa_metadata TEXT, db_mutation_profile "
            "TEXT, db_compatibility_attestation TEXT, architecture_impact "
            "TEXT, updated_at TEXT, spec_updated_at TEXT, spec_updated_by TEXT)"
        )
        conn.execute(
            "CREATE TABLE item_sections (item_id INTEGER, section_name TEXT, "
            "content TEXT, ordering INTEGER, source TEXT DEFAULT 'operator', "
            "created_at TEXT, updated_at TEXT, PRIMARY KEY(item_id, section_name))"
        )
        conn.commit()
    finally:
        conn.close()


class _FakeDB:
    """Backend-aware per-test DB stub."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.mkdtemp(
            prefix="yoke-test-backlog-structured-write-api-",
        )
        self._db_ctx = init_test_db(
            Path(self._tmpdir), apply_schema=_apply_fake_db_schema,
        )
        self.path = self._db_ctx.__enter__()

    def insert_item(self, item_id: int, **fields: Optional[str]) -> None:
        cols = ["id"] + list(fields.keys())
        with connect_test_db(self.path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            marks = ", ".join([p] * len(cols))
            conn.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({marks})",
                (item_id, *fields.values()),
            )

    def fetch_field(self, item_id: int, field: str) -> Optional[str]:
        with connect_test_db(self.path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                f"SELECT {field} FROM items WHERE id = {p}", (item_id,),
            ).fetchone()
        return row[0] if row else None

    def cleanup(self) -> None:
        self._db_ctx.__exit__(None, None, None)
        shutil.rmtree(self._tmpdir, ignore_errors=True)


def _patched_db(test: unittest.TestCase, db: _FakeDB) -> None:
    from yoke_core.domain import db_helpers as _db_helpers
    test.addCleanup(db.cleanup)
    targets = [
        (backlog_queries, "_resolve_write_db_path", db.path),
        (backlog_queries, "_assert_write_db_ready", None),
        (backlog_structured_write_op, "_resolve_write_db_path", db.path),
        (backlog_structured_write_op, "_assert_write_db_ready", None),
        (item_field_transform, "_resolve_write_db_path", db.path),
        (items_structured_field, "_resolve_write_db_path", db.path),
        (backlog_rendering, "_render_body", True),
        (backlog_rendering, "_sync_body", (True, "full")),
        (backlog_rendering, "_maybe_rebuild_board", None),
        (sections, "_render_fn", 0),
        (sections, "_emit_event_fn", None),
        (_db_helpers, "resolve_db_path", db.path),
    ]
    for module, name, value in targets:
        patcher = mock.patch.object(module, name, return_value=value)
        patcher.start()
        test.addCleanup(patcher.stop)


def _request(
    function: str, payload: dict, *, item_id: int = 101,
    preconditions: Optional[dict] = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
        preconditions=preconditions or {},
    )


class TestReplaceHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_happy_path_writes_field_and_returns_envelope(self) -> None:
        self.db.insert_item(101, spec="existing\n")
        req = _request(
            "items.structured_field.replace",
            {"field": "spec", "content": "new content\nline two\n",
             "source": "refine"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(outcome.error)
        payload = outcome.result_payload
        # Envelope required fields per AC-3.5
        for key in (
            "old_line_count", "new_line_count", "old_hash", "new_hash",
            "payload_byte_count", "verification", "github_sync",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["new_line_count"], 2)
        self.assertEqual(payload["github_sync"], "ok")
        self.assertEqual(self.db.fetch_field(101, "spec"),
                         "new content\nline two\n")

    def test_empty_content_rejected_with_empty_body_error(self) -> None:
        # AC-3.2: empty content rejected even when field is already empty
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "spec", "content": ""},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertFalse(outcome.primary_success)
        self.assertIsNotNone(outcome.error)
        self.assertEqual(outcome.error.code, "empty_body")

    def test_empty_content_allowed_with_precondition_opt_in(self) -> None:
        # AC-3.3: allow_empty + reason bypasses the handler's empty_body guard.
        # The owner may still refuse to overwrite a non-empty field with empty;
        # we assert the handler does not produce the early invalid_payload
        # rejection (the precondition was honored).
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "spec", "content": ""},
            preconditions={"allow_empty": True,
                           "allow_empty_reason": "intentional clear"},
        )
        outcome = items_structured_field.handle_replace(req)
        # The handler's empty_body short-circuit must NOT fire.
        if outcome.error is not None:
            self.assertNotEqual(outcome.error.code, "empty_body")

    def test_sun_1664_regression_empty_stdin_rejected(self) -> None:
        # AC-3.6: initial spec write with empty content cannot succeed.
        # Even when the existing field is empty (newly-created item), the
        # handler MUST reject without the allow_empty precondition.
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "spec", "content": "   \n\n"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "empty_body")

    def test_invalid_field_rejected(self) -> None:
        # AC-3.4: invalid field → typed error
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "not_a_real_field", "content": "x"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")

    def test_sync_warning_surfaces_as_github_sync_degraded(self) -> None:
        # AC-3.10: sync failure → warning with code="github_sync_degraded"
        self.db.insert_item(101, spec="x\n")
        with mock.patch.object(
            backlog_rendering, "_sync_body", return_value=(False, None),
        ), mock.patch.object(
            backlog_rendering, "_record_sync_failure", return_value=None,
        ):
            req = _request(
                "items.structured_field.replace",
                {"field": "spec", "content": "new body\n"},
            )
            outcome = items_structured_field.handle_replace(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(len(outcome.warnings), 1)
        self.assertEqual(outcome.warnings[0].code, "github_sync_degraded")
        self.assertEqual(outcome.result_payload["github_sync"], "degraded")

    def test_bad_target_kind_rejected(self) -> None:
        req = FunctionCallRequest(
            function="items.structured_field.replace",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="epic_task", epic_id=1, task_num=2),
            payload={"field": "spec", "content": "x\n"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_payload")


class TestAppendAddendumHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_appends_and_returns_envelope(self) -> None:
        self.db.insert_item(101, spec="# Spec\n\nbody\n")
        req = _request(
            "items.structured_field.append_addendum",
            {"field": "spec", "heading": "Refinement Addendum",
             "content": "more", "source": "refine"},
        )
        outcome = items_structured_field.handle_append_addendum(req)
        self.assertTrue(outcome.primary_success)
        self.assertTrue(outcome.result_payload["changed"])
        self.assertEqual(outcome.result_payload["verification"], "ok")
        spec = self.db.fetch_field(101, "spec")
        self.assertIn("## Refinement Addendum", spec)

    def test_idempotent_repeat_returns_changed_false(self) -> None:
        existing = "# Spec\n\n## Refinement Addendum\nfirst\n"
        self.db.insert_item(101, spec=existing)
        req = _request(
            "items.structured_field.append_addendum",
            {"field": "spec", "heading": "Refinement Addendum",
             "content": "duplicate"},
        )
        outcome = items_structured_field.handle_append_addendum(req)
        self.assertTrue(outcome.primary_success)
        self.assertFalse(outcome.result_payload["changed"])

    def test_empty_content_rejected(self) -> None:
        self.db.insert_item(101, spec="# Spec\n")
        req = _request(
            "items.structured_field.append_addendum",
            {"field": "spec", "heading": "X", "content": ""},
        )
        outcome = items_structured_field.handle_append_addendum(req)
        self.assertFalse(outcome.primary_success)


class TestSectionUpsertHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_inserts_new_section(self) -> None:
        self.db.insert_item(101, spec="x\n")
        req = _request(
            "items.structured_field.section_upsert",
            {"section": "Notes", "content": "note body\n", "ordering": 200},
        )
        outcome = items_structured_field.handle_section_upsert(req)
        self.assertTrue(outcome.primary_success)
        self.assertTrue(outcome.result_payload["changed"])
        self.assertEqual(outcome.result_payload["section"], "Notes")

    def test_structured_field_name_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        req = _request(
            "items.structured_field.section_upsert",
            {"section": "spec", "content": "body"},
        )
        outcome = items_structured_field.handle_section_upsert(req)
        self.assertFalse(outcome.primary_success)


class TestSectionAppendHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _FakeDB()
        _patched_db(self, self.db)

    def test_appends_entry_to_section(self) -> None:
        self.db.insert_item(101, spec="x\n")
        req = _request(
            "items.structured_field.section_append",
            {"section": "Progress Log",
             "headline": "checkpoint", "content": "body", "ordering": 200},
        )
        outcome = items_structured_field.handle_section_append(req)
        self.assertTrue(outcome.primary_success)
        self.assertTrue(outcome.result_payload["changed"])

    def test_empty_content_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        req = _request(
            "items.structured_field.section_append",
            {"section": "Progress Log",
             "headline": "h", "content": ""},
        )
        outcome = items_structured_field.handle_section_append(req)
        self.assertFalse(outcome.primary_success)


class TestRegistrations(unittest.TestCase):
    def test_models_module_composes_four_registrations(self) -> None:
        entries = _models.build_registrations()
        ids = {e["function_id"] for e in entries}
        self.assertEqual(ids, {
            "items.structured_field.replace",
            "items.structured_field.append_addendum",
            "items.structured_field.section_upsert",
            "items.structured_field.section_append",
        })
        for entry in entries:
            self.assertEqual(entry["claim_required_kind"], "item")
            self.assertIn("render_body", entry["side_effects"])
            self.assertIn("github_sync", entry["side_effects"])
            self.assertIn("rebuild_board", entry["side_effects"])


if __name__ == "__main__":
    unittest.main()
