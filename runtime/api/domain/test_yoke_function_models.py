"""Tests for the Yoke function-call envelope models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    FunctionWarning,
    HandlerOutcome,
    TargetRef,
    function_id_pattern,
    validate_function_id,
)


class TestFunctionIdRegex(unittest.TestCase):
    """Function-id regex covers the canonical three-segment shape and
    the two-segment shorthand reserved for families with one operation
    (e.g. ``db_claim.amend``)."""

    def test_three_segments_pass(self):
        self.assertTrue(validate_function_id("items.structured_field.replace"))
        self.assertTrue(validate_function_id("items.structured_field.section_upsert"))
        self.assertTrue(validate_function_id("claims.work.acquire"))
        self.assertTrue(validate_function_id("doctor.run.execute"))

    def test_two_segments_pass(self):
        self.assertTrue(validate_function_id("db_claim.amend"))

    def test_camel_case_fails(self):
        self.assertFalse(validate_function_id("itemsStructuredFieldReplace"))

    def test_double_dot_fails(self):
        self.assertFalse(validate_function_id("items..replace"))

    def test_single_segment_fails(self):
        self.assertFalse(validate_function_id("items"))
        self.assertFalse(validate_function_id(""))

    def test_trailing_dot_fails(self):
        self.assertFalse(validate_function_id("items.field."))

    def test_uppercase_fails(self):
        self.assertFalse(validate_function_id("items.field.Replace"))

    def test_non_string_fails(self):
        self.assertFalse(validate_function_id(None))  # type: ignore[arg-type]
        self.assertFalse(validate_function_id(123))  # type: ignore[arg-type]

    def test_module_exports_pattern(self):
        self.assertIsNotNone(function_id_pattern.match("a.b.c"))


class TestActorContext(unittest.TestCase):
    def test_session_id_required(self):
        with self.assertRaises(ValidationError):
            ActorContext()  # type: ignore[call-arg]
        with self.assertRaises(ValidationError):
            ActorContext(actor_id="op-1")  # type: ignore[call-arg]

    def test_actor_id_defaults_to_none(self):
        actor = ActorContext(session_id="s-1")
        self.assertIsNone(actor.actor_id)
        self.assertEqual(actor.session_id, "s-1")

    def test_round_trip(self):
        actor = ActorContext(actor_id="op-1", session_id="s-1")
        self.assertEqual(actor.actor_id, "op-1")
        self.assertEqual(actor.session_id, "s-1")


class TestTargetRef(unittest.TestCase):
    def test_item_kind_minimal(self):
        target = TargetRef(kind="item", item_id=42)
        self.assertEqual(target.kind, "item")
        self.assertEqual(target.item_id, 42)

    def test_epic_task_kind(self):
        target = TargetRef(kind="epic_task", epic_id=1665, task_num=1)
        self.assertEqual(target.epic_id, 1665)
        self.assertEqual(target.task_num, 1)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValidationError):
            TargetRef(kind="not_a_kind")  # type: ignore[arg-type]


class TestEnvelope(unittest.TestCase):
    def _request(self):
        return FunctionCallRequest(
            function="items.scalar.update",
            actor=ActorContext(actor_id="op-1", session_id="s-1"),
            target=TargetRef(kind="item", item_id=42),
        )

    def test_request_defaults(self):
        req = self._request()
        self.assertEqual(req.version, "v1")
        self.assertEqual(req.payload, {})
        self.assertEqual(req.preconditions, {})
        self.assertEqual(req.options, {})
        self.assertIsNone(req.request_id)

    def test_request_function_required(self):
        with self.assertRaises(ValidationError):
            FunctionCallRequest(
                actor=ActorContext(actor_id="op-1", session_id="s-1"),
                target=TargetRef(kind="item", item_id=42),
            )  # type: ignore[call-arg]

    def test_response_shape(self):
        resp = FunctionCallResponse(
            success=True,
            function="items.scalar.update",
            version="v1",
        )
        self.assertTrue(resp.success)
        self.assertEqual(resp.result, {})
        self.assertEqual(resp.warnings, [])
        self.assertIsNone(resp.error)
        self.assertEqual(resp.event_ids, [])

    def test_warning_and_error_shape(self):
        warning = FunctionWarning(
            code="github_sync_degraded",
            step="github_sync",
            detail="rate-limited",
        )
        error = FunctionError(code="empty_body", message="payload empty")
        self.assertIsNone(warning.recovery_function)
        self.assertIsNone(error.jsonpath)


class TestFunctionErrorRecoveryHint(unittest.TestCase):
    """``recovery_hint`` carries this failure's own recovery step, or
    nothing. No generic directive is appended to every error envelope."""

    def test_absent_recovery_hint_stays_absent(self):
        err = FunctionError(code="empty_body", message="payload empty")
        self.assertIsNone(err.recovery_hint)

    def test_existing_recovery_hint_is_left_verbatim(self):
        hint = "See .yoke/docs/reference/db-reference/functions.md."
        err = FunctionError(
            code="payload_invalid", message="bad payload", recovery_hint=hint,
        )
        self.assertEqual(err.recovery_hint, hint)

    def test_no_field_note_directive_on_any_error(self):
        err = FunctionError(code="x", message="y")
        self.assertNotIn(FIELD_NOTE_FOOTER, err.recovery_hint or "")
        with_hint = FunctionError(code="x", message="y", recovery_hint="Retry.")
        self.assertNotIn(FIELD_NOTE_FOOTER, with_hint.recovery_hint)

    def test_round_trip_preserves_recovery_hint(self):
        err = FunctionError(code="x", message="y", recovery_hint="Retry.")
        replayed = FunctionError.model_validate(err.model_dump())
        self.assertEqual(replayed.recovery_hint, "Retry.")
        self.assertEqual(err.model_copy().recovery_hint, "Retry.")

    def test_response_envelope_error_carries_no_directive(self):
        resp = FunctionCallResponse(
            success=False,
            function="items.scalar.update",
            version="v1",
            error=FunctionError(code="frozen", message="item is frozen"),
        )
        self.assertIsNone(resp.error.recovery_hint)


class TestHandlerOutcome(unittest.TestCase):
    def test_default_fields(self):
        outcome = HandlerOutcome()
        self.assertEqual(outcome.result_payload, {})
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.warnings, [])
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.side_effects_to_run, [])
        self.assertEqual(outcome.handler_event_ids, [])

    def test_warning_payload(self):
        outcome = HandlerOutcome(
            primary_success=True,
            warnings=[
                FunctionWarning(
                    code="board_rebuild_degraded",
                    step="board",
                    detail="rebuild raised",
                )
            ],
        )
        self.assertEqual(len(outcome.warnings), 1)
        self.assertEqual(outcome.warnings[0].step, "board")


if __name__ == "__main__":
    unittest.main()
