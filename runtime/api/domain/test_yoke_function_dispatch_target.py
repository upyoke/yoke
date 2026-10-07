"""Server-side target item-ref resolution tests (relay contract).

Covers :mod:`yoke_core.domain.yoke_function_dispatch_target`: raw
``target.public_ref`` values resolve into ``target.item_id`` inside the
dispatcher from explicit project context, and unresolvable refs return a
typed ``public_ref_unresolved`` envelope.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from yoke_core.domain.item_ref_resolution import ItemRefError
from yoke_core.domain.yoke_function_dispatch_target import (
    resolve_target_public_ref,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _request(target: TargetRef, session_id: str = "s-1") -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.get.run",
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=target,
    )


class TestResolveTargetItemRef(unittest.TestCase):
    def test_noop_without_item_ref(self):
        request = _request(TargetRef(kind="item", item_id=42))
        self.assertIsNone(resolve_target_public_ref(request))
        self.assertEqual(request.target.item_id, 42)

    def test_mismatched_item_id_and_ref_is_refused(self):
        request = _request(
            TargetRef(kind="item", item_id=42, public_ref="YOK-99"),
        )

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                side_effect=lambda *a, **kw: _cm(),
            ),
            patch(
                "yoke_core.domain.item_ref_resolution.resolve_item_ref",
                return_value=99,
            ),
        ):
            response = resolve_target_public_ref(request)
        assert response is not None
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "item_id_ref_mismatch")
        self.assertNotIn("42", response.error.message)
        self.assertEqual(request.target.item_id, 42)

    def test_matching_item_id_and_ref_keeps_resolved_id(self):
        request = _request(
            TargetRef(kind="item", item_id=42, public_ref="YOK-99"),
        )

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                side_effect=lambda *a, **kw: _cm(),
            ),
            patch(
                "yoke_core.domain.item_ref_resolution.resolve_item_ref",
                return_value=42,
            ),
        ):
            self.assertIsNone(resolve_target_public_ref(request))
        self.assertEqual(request.target.item_id, 42)
        self.assertIsNone(request.target.project_id)

    def test_resolves_ref_with_target_project_context(self):
        request = _request(
            TargetRef(kind="item", public_ref=f"YOK-{123}", project_id="yoke"),
        )
        captured = {}

        def _parse(conn, ref, *, project=None):
            captured["ref"] = ref
            captured["project"] = project
            return 4242

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                side_effect=lambda *a, **kw: _cm(),
            ),
            patch(
                "yoke_core.domain.item_ref_resolution.resolve_item_ref",
                side_effect=_parse,
            ),
        ):
            self.assertIsNone(resolve_target_public_ref(request))
        self.assertEqual(request.target.item_id, 4242)
        self.assertEqual(captured["ref"], f"YOK-{123}")
        self.assertEqual(captured["project"], "yoke")
        # The ambient context hint is cleared after resolution so
        # permission scoping derives from the item's own project.
        self.assertIsNone(request.target.project_id)

    def test_unresolved_ref_returns_typed_error(self):
        request = _request(TargetRef(kind="item", public_ref=f"YOK-{123}"))

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                side_effect=lambda *a, **kw: _cm(),
            ),
            patch(
                "yoke_core.domain.item_ref_resolution.resolve_item_ref",
                side_effect=ItemRefError(
                    "item_ref_not_found",
                    "no item for the requested reference",
                ),
            ),
        ):
            response = resolve_target_public_ref(request)
        assert response is not None
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "public_ref_unresolved")
        self.assertIn("no item for the requested reference", response.error.message)

    def test_epic_task_ref_resolves_onto_epic_id(self):
        request = _request(
            TargetRef(kind="epic_task", public_ref="YOK-7", task_num=3),
        )

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with (
            patch(
                "yoke_core.domain.db_helpers.connect",
                side_effect=lambda *a, **kw: _cm(),
            ),
            patch(
                "yoke_core.domain.item_ref_resolution.resolve_item_ref",
                return_value=5150,
            ),
        ):
            self.assertIsNone(resolve_target_public_ref(request))
        self.assertEqual(request.target.epic_id, 5150)
        self.assertIsNone(request.target.item_id)
        self.assertEqual(request.target.task_num, 3)


if __name__ == "__main__":
    unittest.main()
