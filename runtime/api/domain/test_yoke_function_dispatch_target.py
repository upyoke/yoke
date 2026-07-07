"""Server-side target item-ref resolution tests (relay contract).

Covers :mod:`yoke_core.domain.yoke_function_dispatch_target`: raw
``target.item_ref`` values resolve into ``target.item_id`` inside the
dispatcher with the explicit-context -> session-context ladder, and
unresolvable refs return a typed ``item_ref_unresolved`` envelope.
"""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import patch

from yoke_core.domain import yoke_function_dispatch_target as target_module
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

    def test_explicit_item_id_wins_over_ref(self):
        request = _request(
            TargetRef(kind="item", item_id=42, item_ref="YOK-99"),
        )
        self.assertIsNone(resolve_target_item_ref(request))
        self.assertEqual(request.target.item_id, 42)

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

    def test_falls_back_to_session_project_context(self):
        request = _request(TargetRef(kind="item", item_ref="123"))

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        captured = {}

        def _parse(ref, *, project=None, conn=None, allow_bare_internal=False):
            captured["project"] = project
            return 17

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch.object(
            target_module, "_session_project_context", return_value=7,
        ), patch(
            "yoke_core.domain.yok_n_parser.parse_item_id",
            side_effect=_parse,
        ):
            self.assertIsNone(resolve_target_item_ref(request))
        self.assertEqual(request.target.item_id, 17)
        self.assertEqual(captured["project"], 7)

    def test_unresolved_ref_returns_typed_error(self):
        request = _request(TargetRef(kind="item", item_ref="123"))

        @contextmanager
        def _cm(*_a, **_k):
            yield object()

        with patch(
            "yoke_core.domain.db_helpers.connect",
            side_effect=lambda *a, **kw: _cm(),
        ), patch.object(
            target_module, "_session_project_context", return_value=None,
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


class TestSessionProjectContext(unittest.TestCase):
    """Session-context inference against a disposable-Postgres double."""

    def setUp(self) -> None:
        from runtime.api.fixtures import pg_testdb
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

        name = pg_testdb.create_test_database()
        self.conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name
        )
        apply_fixture_ddl(
            self.conn,
            "CREATE TABLE harness_sessions (session_id TEXT PRIMARY KEY, "
            "current_item_id TEXT, recent_item_id TEXT);"
            "CREATE TABLE items (id INTEGER PRIMARY KEY, project_id INTEGER);",
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_current_item_project_wins(self):
        self.conn.execute("INSERT INTO items VALUES (10, 2)")
        self.conn.execute(
            "INSERT INTO harness_sessions VALUES ('s-1', '10', NULL)"
        )
        self.conn.commit()
        self.assertEqual(
            target_module._session_project_context(self.conn, "s-1"), 2,
        )

    def test_recent_item_fallback(self):
        self.conn.execute("INSERT INTO items VALUES (11, 3)")
        self.conn.execute(
            "INSERT INTO harness_sessions VALUES ('s-2', NULL, '11')"
        )
        self.conn.commit()
        self.assertEqual(
            target_module._session_project_context(self.conn, "s-2"), 3,
        )

    def test_unknown_session_returns_none(self):
        self.assertIsNone(
            target_module._session_project_context(self.conn, "nope"),
        )

    def test_blank_session_returns_none(self):
        self.assertIsNone(
            target_module._session_project_context(self.conn, ""),
        )


if __name__ == "__main__":
    unittest.main()
