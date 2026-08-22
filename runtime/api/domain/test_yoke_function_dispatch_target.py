"""Server-side target item-ref resolution tests (relay contract).

Covers :mod:`yoke_core.domain.yoke_function_dispatch_target`: raw
``target.item_ref`` values resolve into ``target.item_id`` inside the
dispatcher from explicit project context, and unresolvable refs return a
typed ``item_ref_unresolved`` envelope.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from yoke_core.domain.yoke_function_dispatch_target import (
    resolve_target_item_ref,
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
        self.assertIsNone(resolve_target_item_ref(request))
        self.assertEqual(request.target.item_id, 42)

    def test_mismatched_item_id_and_ref_is_refused(self):
        request = _request(
            TargetRef(kind="item", item_id=42, item_ref="YOK-99"),
        )

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch(
            "yoke_core.domain.yok_n_parser.parse_item_id",
            return_value=99,
        ):
            response = resolve_target_item_ref(request)
        assert response is not None
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "item_id_ref_mismatch")
        self.assertEqual(request.target.item_id, 42)

    def test_matching_item_id_and_ref_keeps_resolved_id(self):
        request = _request(
            TargetRef(kind="item", item_id=42, item_ref="YOK-99"),
        )

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch(
            "yoke_core.domain.yok_n_parser.parse_item_id",
            return_value=42,
        ):
            self.assertIsNone(resolve_target_item_ref(request))
        self.assertEqual(request.target.item_id, 42)
        self.assertIsNone(request.target.project_id)

    def test_resolves_ref_with_target_project_context(self):
        request = _request(
            TargetRef(kind="item", item_ref="123", project_id="yoke"),
        )
        captured = {}

        def _parse(ref, *, project=None, conn=None, allow_bare_internal=False):
            captured["ref"] = ref
            captured["project"] = project
            return 4242

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch(
            "yoke_core.domain.yok_n_parser.parse_item_id",
            side_effect=_parse,
        ):
            self.assertIsNone(resolve_target_item_ref(request))
        self.assertEqual(request.target.item_id, 4242)
        self.assertEqual(captured["ref"], "123")
        self.assertEqual(captured["project"], "yoke")
        # The ambient context hint is cleared after resolution so
        # permission scoping derives from the item's own project.
        self.assertIsNone(request.target.project_id)

    def test_unresolved_ref_returns_typed_error(self):
        request = _request(TargetRef(kind="item", item_ref="123"))

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch(
            "yoke_core.domain.yok_n_parser.parse_item_id",
            side_effect=ValueError("bare numeric item refs are project-local"),
        ):
            response = resolve_target_item_ref(request)
        assert response is not None
        self.assertFalse(response.success)
        assert response.error is not None
        self.assertEqual(response.error.code, "item_ref_unresolved")
        self.assertIn("project-local", response.error.message)
if __name__ == "__main__":
    unittest.main()
