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


_FIXTURE_ITEM_REF = f"YOK-{42}"


def _request(payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.get.run",
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="item", item_id=42),
        payload=payload or {},
    )


class TestItemsGetDefaultProjection(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(reads, "_read_instructions", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        sections = patch(
            "yoke_core.domain.render_body_item_sections.fetch_item_sections",
            side_effect=lambda conn, item_id, *, late: (
                [{"section_name": "Progress Log", "content": "Checkpoint"}]
                if late else []
            ),
        )
        sections.start()
        self.addCleanup(sections.stop)

    def test_default_projection_includes_structured_and_additional_fields(self):
        # Stored text appears once; body stays available as an explicit read.
        queried = []

        def fake_query_item(item_id, col, db_path=None):
            queried.append(col)
            return f"seeded-{col}"

        with (
            patch(
                "yoke_core.domain.project_identity.render_item_ref",
                return_value=_FIXTURE_ITEM_REF,
            ),
            patch(
                "yoke_core.domain.items_queries.query_item",
                side_effect=fake_query_item,
            ),
            patch(
                "yoke_core.domain.item_completion_flow_projection.completion_flow_values",
                return_value={
                    42: {"value": "default-flow", "source": "project_default"}
                },
            ),
        ):
            outcome = reads.handle_items_get(_request({}))
        self.assertTrue(outcome.primary_success)
        fields = outcome.result_payload["fields"]
        for field in STRUCTURED_FIELDS:
            self.assertIn(field, fields)
            self.assertEqual(fields[field], f"seeded-{field}")
        for field in ADDITIONAL_SCALAR_FIELDS:
            self.assertIn(field, fields)
        self.assertEqual(
            queried,
            [
                field
                for field in DEFAULT_GET_FIELDS
                if field not in {"id", "deployment_flow"}
            ],
        )
        self.assertEqual(
            fields["deployment_flow"],
            {"value": "default-flow", "source": "project_default"},
        )
        self.assertEqual(fields["id"], _FIXTURE_ITEM_REF)
        self.assertEqual(set(fields), set(DEFAULT_GET_FIELDS))
        self.assertNotIn("body", fields)
        self.assertEqual(outcome.result_payload["sections"], [
            {"name": "Progress Log", "content": "Checkpoint"},
        ])

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
        self.assertNotIn("sections", outcome.result_payload)

    def test_explicit_body_still_renders_the_complete_item(self):
        with patch(
            "yoke_core.domain.items_queries.query_item",
            return_value="## Spec\nScope\n## Progress Log\nCheckpoint",
        ) as query:
            outcome = reads.handle_items_get(_request({"fields": ["body"]}))
        query.assert_called_once_with(42, "body")
        self.assertIn("Checkpoint", outcome.result_payload["fields"]["body"])
        self.assertNotIn("sections", outcome.result_payload)
