"""Unit tests for read-family handlers registered by task 7.

Covers handlers in ``yoke_core.domain.handlers.reads`` and
``yoke_core.domain.handlers.reads_misc``:

- ``items.get.run``
- ``epic_tasks.list.run``
- ``path_claims.conflicts.list``
- ``doctor.run.run``
- ``projects.capability.has`` (AC-7.9)

The events.* read handlers are covered by
``runtime/api/domain/handlers/test_events_reads.py``.

Tests call the handlers directly with synthetic envelopes instead of routing
through the FastAPI surface (covered by ``test_api_yoke_functions``).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from yoke_core.domain.handlers import reads, reads_misc
from yoke_core.domain.items_constants import STRUCTURED_FIELDS
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(function_id: str, target: TargetRef, payload=None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=target,
        payload=payload or {},
    )


class TestItemsGet(unittest.TestCase):
    def test_rejects_non_item_target(self):
        req = _request("items.get.run", TargetRef(kind="global"))
        outcome = reads.handle_items_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_rejects_unknown_field(self):
        req = _request(
            "items.get.run",
            TargetRef(kind="item", item_id=42),
            payload={"fields": ["definitely_not_a_column"]},
        )
        outcome = reads.handle_items_get(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_returns_typed_fields_for_known_columns(self):
        captured = {}

        def fake_query_item(item_id, col, db_path=None):
            captured.setdefault(item_id, []).append(col)
            return {"id": "42", "title": "fake"}.get(col, "")

        with patch.object(reads, "__name__", reads.__name__):
            with patch(
                "yoke_core.domain.items_queries.query_item",
                side_effect=fake_query_item,
            ):
                req = _request(
                    "items.get.run",
                    TargetRef(kind="item", item_id=42),
                    payload={"fields": ["id", "title"]},
                )
                outcome = reads.handle_items_get(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["item_id"], 42)
        self.assertEqual(
            outcome.result_payload["fields"],
            {"id": "42", "title": "fake"},
        )

    def test_accepts_additional_scalar_fields(self):
        # Regression: packet promised blocked/owner/etc as items columns but
        # items.get rejected them because _ALLOWED_GET_FIELDS was derived
        # solely from the older CANONICAL_COLUMNS tuple. Pull the set the
        # handler uses directly so future additions stay tested.
        additional = sorted(reads._ADDITIONAL_SCALAR_GET_FIELDS)
        self.assertIn("blocked", additional)
        self.assertIn("owner", additional)

        def fake_query_item(item_id, col, db_path=None):
            return f"seeded-{col}"

        for field in additional:
            with self.subTest(field=field):
                with patch(
                    "yoke_core.domain.items_queries.query_item",
                    side_effect=fake_query_item,
                ):
                    req = _request(
                        "items.get.run",
                        TargetRef(kind="item", item_id=42),
                        payload={"fields": [field]},
                    )
                    outcome = reads.handle_items_get(req)
                self.assertTrue(
                    outcome.primary_success,
                    msg=f"items.get.run rejected scalar field {field!r}",
                )
                self.assertEqual(
                    outcome.result_payload["fields"][field],
                    f"seeded-{field}",
                )

    def test_accepts_structured_fields(self):
        # Parametrization sourced from the live STRUCTURED_FIELDS frozenset
        # so new entries are exercised automatically.
        def fake_query_item(item_id, col, db_path=None):
            return f"seeded-{col}"

        for field in sorted(STRUCTURED_FIELDS):
            with self.subTest(field=field):
                with patch(
                    "yoke_core.domain.items_queries.query_item",
                    side_effect=fake_query_item,
                ):
                    req = _request(
                        "items.get.run",
                        TargetRef(kind="item", item_id=42),
                        payload={"fields": [field]},
                    )
                    outcome = reads.handle_items_get(req)
                self.assertTrue(
                    outcome.primary_success,
                    msg=f"items.get.run rejected structured field {field!r}",
                )
                self.assertEqual(
                    outcome.result_payload["fields"][field],
                    f"seeded-{field}",
                )


class TestEpicTasksList(unittest.TestCase):
    def test_rejects_missing_epic_id(self):
        req = _request(
            "epic_tasks.list.run", TargetRef(kind="item", item_id=99),
        )
        outcome = reads.handle_epic_tasks_list(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "target_invalid")

    def test_returns_typed_task_list(self):
        rows = [
            (1, 7, 1, "t1", "planned", "wt", "deps"),
            (2, 7, 2, "t2", "implementing", "", ""),
        ]

        class _Conn:
            def execute(self, *args, **kwargs):
                class _R:
                    def fetchall(self_inner):
                        return rows

                return _R()

            def close(self):
                pass

        with patch(
            "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
        ):
            req = _request(
                "epic_tasks.list.run",
                TargetRef(kind="item", item_id=999, epic_id=7),
            )
            outcome = reads.handle_epic_tasks_list(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(outcome.result_payload["epic_id"], 7)
        self.assertEqual(len(outcome.result_payload["tasks"]), 2)
        self.assertEqual(outcome.result_payload["tasks"][0]["task_num"], 1)


class TestPathClaimsConflicts(unittest.TestCase):
    def test_filters_by_item_id(self):
        conflicts = [
            {"self": {"item_id": 42}, "other": {"item_id": 99}},
            {"self": {"item_id": 1}, "other": {"item_id": 2}},
        ]
        with patch(
            "yoke_core.domain.path_claims_read.cross_claim_conflicts",
            return_value=conflicts,
        ):
            with patch("yoke_core.domain.db_helpers.connect"):
                req = _request(
                    "path_claims.conflicts.list",
                    TargetRef(kind="item", item_id=42),
                )
                outcome = reads_misc.handle_path_claims_conflicts(req)
        self.assertTrue(outcome.primary_success)
        self.assertEqual(len(outcome.result_payload["conflicts"]), 1)


class TestDoctorRun(unittest.TestCase):
    def test_returns_structured_results(self):
        # Stub the doctor registry to a tiny list so the test does not hit
        # real DB state.
        from yoke_core.engines.doctor_registry_types import HealthCheck

        def _fake_hc_fn(conn, args, rec):
            rec.record("HC-fake", "Fake HC", "PASS", "all good")

        fake_hcs = [HealthCheck(slug="fake", name="Fake HC", fn=_fake_hc_fn)]

        class _Conn:
            def close(self):
                pass

        with patch(
            "yoke_core.engines.doctor_registry.HEALTH_CHECKS", fake_hcs,
        ):
            with patch(
                "yoke_core.domain.db_helpers.connect", return_value=_Conn(),
            ):
                req = _request(
                    "doctor.run.run", TargetRef(kind="global"),
                    payload={"only": "fake", "project": "yoke"},
                )
                outcome = reads_misc.handle_doctor_run(req)
        self.assertTrue(outcome.primary_success)
        results = outcome.result_payload["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["hc"], "HC-fake")
        self.assertEqual(results[0]["severity"], "PASS")


class TestProjectsCapabilityHas(unittest.TestCase):
    """AC-7.9 — typed boolean replacement for ``has-capability ... 2>&1; echo``."""

    def test_rejects_missing_project(self):
        req = _request(
            "projects.capability.has", TargetRef(kind="global"),
            payload={"cap_type": "migration_model"},
        )
        outcome = reads_misc.handle_projects_capability_has(req)
        self.assertFalse(outcome.primary_success)
        self.assertEqual(outcome.error.code, "payload_invalid")

    def test_rejects_missing_cap_type(self):
        req = _request(
            "projects.capability.has", TargetRef(kind="global"),
            payload={"project": "yoke"},
        )
        outcome = reads_misc.handle_projects_capability_has(req)
        self.assertFalse(outcome.primary_success)

    def test_returns_typed_boolean_true(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_has_capability",
            return_value=True,
        ):
            req = _request(
                "projects.capability.has", TargetRef(kind="global"),
                payload={"project": "yoke", "cap_type": "migration_model"},
            )
            outcome = reads_misc.handle_projects_capability_has(req)
        self.assertTrue(outcome.primary_success)
        self.assertIs(outcome.result_payload["has"], True)
        self.assertEqual(outcome.result_payload["project"], "yoke")

    def test_returns_typed_boolean_false(self):
        with patch(
            "yoke_core.domain.projects_crud.cmd_has_capability",
            return_value=False,
        ):
            req = _request(
                "projects.capability.has", TargetRef(kind="global"),
                payload={"project": "externalwebapp", "cap_type": "fake_capability"},
            )
            outcome = reads_misc.handle_projects_capability_has(req)
        self.assertTrue(outcome.primary_success)
        self.assertIs(outcome.result_payload["has"], False)


if __name__ == "__main__":
    unittest.main()
