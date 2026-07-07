"""Regression tests for function-call structured-field board rebuilds."""

from __future__ import annotations

import unittest
from unittest import mock

from yoke_core.domain import item_field_transform
from yoke_core.domain.handlers import items_structured_field
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=101),
        payload=payload,
    )


class TestStructuredFieldHandlersSuppressBoardRebuild(unittest.TestCase):
    def test_append_addendum_handler_passes_rebuild_board_false(self) -> None:
        result = item_field_transform.TransformResult(
            success=True,
            operation="append-addendum",
            item_id=101,
            field="spec",
            heading="Notes",
            changed=True,
            old_line_count=1,
            new_line_count=3,
            verification="ok",
        )
        with mock.patch.object(
            item_field_transform, "append_addendum", return_value=result,
        ) as patched:
            outcome = items_structured_field.handle_append_addendum(
                _request(
                    "items.structured_field.append_addendum",
                    {"field": "spec", "heading": "Notes", "content": "body"},
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertFalse(patched.call_args.kwargs["rebuild_board"])

    def test_section_upsert_handler_passes_rebuild_board_false(self) -> None:
        result = item_field_transform.TransformResult(
            success=True,
            operation="section-upsert",
            item_id=101,
            section="File Budget",
            changed=True,
            new_line_count=3,
            verification="ok",
        )
        with mock.patch.object(
            item_field_transform, "section_upsert", return_value=result,
        ) as patched:
            outcome = items_structured_field.handle_section_upsert(
                _request(
                    "items.structured_field.section_upsert",
                    {"section": "File Budget", "content": "body"},
                )
            )
        self.assertTrue(outcome.primary_success)
        self.assertFalse(patched.call_args.kwargs["rebuild_board"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
