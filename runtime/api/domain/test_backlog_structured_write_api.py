"""Unit tests for structured-field handler wrappers and registrations."""

from __future__ import annotations

from runtime.api.domain.backlog_structured_write_api_test_support import (
    _FakeDB as _FakeDB,
    _apply_fake_db_schema as _apply_fake_db_schema,
    _patched_db as _patched_db,
)


import unittest
from typing import Optional
from unittest import mock

from yoke_core.domain import (
    backlog_rendering,
)
from yoke_core.domain.handlers import (
    items_structured_field,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(
    function: str,
    payload: dict,
    *,
    item_id: int = 101,
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
            {"field": "spec", "content": "new content\nline two\n", "source": "refine"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertTrue(outcome.primary_success)
        self.assertIsNone(outcome.error)
        payload = outcome.result_payload
        # Envelope required fields
        for key in (
            "old_line_count",
            "new_line_count",
            "old_hash",
            "new_hash",
            "payload_byte_count",
            "verification",
            "github_sync",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["new_line_count"], 2)
        self.assertEqual(payload["github_sync"], "ok")
        self.assertEqual(self.db.fetch_field(101, "spec"), "new content\nline two\n")

    def test_empty_content_rejected_with_empty_body_error(self) -> None:
        # Empty content rejected even when field is already empty
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
        # Allow_empty + reason bypasses the handler's empty_body guard.
        # The owner may still refuse to overwrite a non-empty field with empty;
        # we assert the handler does not produce the early invalid_payload
        # rejection (the precondition was honored).
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "spec", "content": ""},
            preconditions={
                "allow_empty": True,
                "allow_empty_reason": "intentional clear",
            },
        )
        outcome = items_structured_field.handle_replace(req)
        # The handler's empty_body short-circuit must NOT fire.
        if outcome.error is not None:
            self.assertNotEqual(outcome.error.code, "empty_body")

    def test_empty_stdin_rejected(self) -> None:
        # Initial spec write with empty content cannot succeed.
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
        # Invalid field → typed error
        self.db.insert_item(101, spec=None)
        req = _request(
            "items.structured_field.replace",
            {"field": "not_a_real_field", "content": "x"},
        )
        outcome = items_structured_field.handle_replace(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "invalid_field")

    def test_sync_warning_surfaces_as_github_sync_degraded(self) -> None:
        # Sync failure → warning with code="github_sync_degraded"
        self.db.insert_item(101, spec="x\n")
        with (
            mock.patch.object(
                backlog_rendering,
                "_sync_body",
                return_value=(False, None),
            ),
            mock.patch.object(
                backlog_rendering,
                "_record_sync_failure",
                return_value=None,
            ),
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
            {
                "field": "spec",
                "heading": "Refinement Addendum",
                "content": "more",
                "source": "refine",
            },
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
            {"field": "spec", "heading": "Refinement Addendum", "content": "duplicate"},
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
            {
                "section": "Progress Log",
                "headline": "checkpoint",
                "content": "body",
                "ordering": 200,
            },
        )
        outcome = items_structured_field.handle_section_append(req)
        self.assertTrue(outcome.primary_success)
        self.assertTrue(outcome.result_payload["changed"])

    def test_empty_content_rejected(self) -> None:
        self.db.insert_item(101, spec="x\n")
        req = _request(
            "items.structured_field.section_append",
            {"section": "Progress Log", "headline": "h", "content": ""},
        )
        outcome = items_structured_field.handle_section_append(req)
        self.assertFalse(outcome.primary_success)
