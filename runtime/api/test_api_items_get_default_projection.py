"""Default and subset projection for items.get.run."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import reads
from yoke_core.domain.items_constants import STRUCTURED_FIELDS
from yoke_contracts.items_projection import (
    ADDITIONAL_SCALAR_FIELDS,
    DEFAULT_GET_FIELDS,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.get.run",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=42),
        payload=payload or {},
    )


class TestItemsGetDefaultProjection(unittest.TestCase):
    def test_default_projection_includes_structured_and_additional_fields(self):
        # Empty payload.fields must project every allowed field so
        # `yoke items get ITEM --json` does not hide technical_plan etc.
        queried = []

        def fake_query_item(item_id, col, db_path=None):
            queried.append(col)
            return f"seeded-{col}"

        with patch(
            "yoke_core.domain.items_queries.query_item",
            side_effect=fake_query_item,
        ):
            outcome = reads.handle_items_get(_request({}))
        self.assertTrue(outcome.primary_success)
        fields = outcome.result_payload["fields"]
        for field in STRUCTURED_FIELDS:
            self.assertIn(field, fields)
            self.assertEqual(fields[field], f"seeded-{field}")
        for field in ADDITIONAL_SCALAR_FIELDS:
            self.assertIn(field, fields)
        self.assertEqual(queried, list(DEFAULT_GET_FIELDS))
        self.assertEqual(set(fields), set(DEFAULT_GET_FIELDS))

    def test_explicit_field_subset_still_projects_only_requested(self):
        queried = []

        def fake_query_item(item_id, col, db_path=None):
            queried.append(col)
            return f"seeded-{col}"

        with patch(
            "yoke_core.domain.items_queries.query_item",
            side_effect=fake_query_item,
        ):
            outcome = reads.handle_items_get(
                _request({"fields": ["title", "technical_plan"]}),
            )
        self.assertTrue(outcome.primary_success)
        self.assertEqual(
            outcome.result_payload["fields"],
            {
                "title": "seeded-title",
                "technical_plan": "seeded-technical_plan",
            },
        )
        self.assertEqual(queried, ["title", "technical_plan"])
