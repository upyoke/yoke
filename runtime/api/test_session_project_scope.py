"""Unit tests for ``session_project_scope``.

Covers AC-1 (exports), AC-2 (all-projects default), AC-3 (explicit override
+ unknown-id error), AC-4 (CLI arg parser), and AC-11 (backward-compat
behavior when no override is supplied — equivalent to all-projects default).
"""

from __future__ import annotations

import unittest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.session_project_scope import (
    parse_project_cli_arg,
    resolve_session_project_scope,
)


PROJECTS_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
"""

PROJECT_IDS = {
    "yoke": 1,
    "externalwebapp": 2,
    "third": 3,
    "scope-fixture-alpha": 4,
}


def _project_id(project: str) -> int:
    return PROJECT_IDS.get(project, max(PROJECT_IDS.values()) + 1)


def _make_disposable_db():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )


def _make_db(project_ids: list[str]):
    conn = _make_disposable_db()
    apply_fixture_ddl(conn, PROJECTS_SCHEMA)
    for project_id in project_ids:
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (%s, %s, %s, %s)",
            (
                _project_id(project_id),
                project_id,
                project_id.title(),
                "YOK",
            ),
        )
    conn.commit()
    return conn


class TestResolveSessionProjectScope(unittest.TestCase):
    """AC-2, AC-3: all-projects default + override semantics."""

    def test_returns_all_registered_projects_when_override_is_none(self) -> None:
        """AC-2: ``override=None`` returns every row in ``projects`` — never
        the literal ``"yoke"`` fallback."""
        conn = _make_db(["yoke", "externalwebapp"])
        try:
            self.assertEqual(
                sorted(resolve_session_project_scope(conn, override=None)),
                [1, 2],
            )
        finally:
            conn.close()

    def test_returns_all_registered_projects_when_override_is_empty_list(self) -> None:
        """AC-2: ``override=[]`` is treated as no override (all-projects)."""
        conn = _make_db(["yoke", "externalwebapp"])
        try:
            self.assertEqual(
                sorted(resolve_session_project_scope(conn, override=[])),
                [1, 2],
            )
        finally:
            conn.close()

    def test_does_not_fall_back_to_literal_yoke(self) -> None:
        """AC-2 contract: a ``projects`` row whose id is NOT ``yoke`` must
        appear in the default scope. The prior silent ``"yoke"`` fallback
        must not return."""
        conn = _make_db(["externalwebapp"])
        try:
            self.assertEqual(
                resolve_session_project_scope(conn, override=None),
                [2],
            )
        finally:
            conn.close()

    def test_empty_projects_returns_empty_list_when_no_override(self) -> None:
        """Edge case: empty registry returns ``[]``."""
        conn = _make_db([])
        try:
            self.assertEqual(
                resolve_session_project_scope(conn, override=None),
                [],
            )
        finally:
            conn.close()

    def test_returns_override_unchanged_when_all_valid(self) -> None:
        """AC-3: non-empty override returns the list unchanged (order
        preserved)."""
        conn = _make_db(["yoke", "externalwebapp", "third"])
        try:
            self.assertEqual(
                resolve_session_project_scope(conn, override=["externalwebapp", "yoke"]),
                [2, 1],
            )
        finally:
            conn.close()

    def test_unknown_override_id_raises_with_id_and_registered_set(self) -> None:
        """AC-3: unknown override id raises a clear error naming the unknown
        id and the registered set."""
        conn = _make_db(["yoke", "externalwebapp"])
        try:
            with self.assertRaises(ValueError) as cm:
                resolve_session_project_scope(conn, override=["unknown"])
            message = str(cm.exception)
            self.assertIn("unknown", message)
            self.assertIn("yoke", message)
            self.assertIn("externalwebapp", message)
        finally:
            conn.close()

    def test_partial_unknown_override_raises(self) -> None:
        """AC-3: an override mixing known + unknown ids still raises."""
        conn = _make_db(["yoke", "externalwebapp"])
        try:
            with self.assertRaises(ValueError):
                resolve_session_project_scope(
                    conn, override=["yoke", "ghost"]
                )
        finally:
            conn.close()


class TestParseProjectCliArg(unittest.TestCase):
    """AC-4: CLI arg parser behavior."""

    def test_none_input_returns_none(self) -> None:
        self.assertIsNone(parse_project_cli_arg(None))

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(parse_project_cli_arg(""))

    def test_whitespace_only_returns_none(self) -> None:
        self.assertIsNone(parse_project_cli_arg("   "))

    def test_single_id_returns_singleton(self) -> None:
        self.assertEqual(parse_project_cli_arg("yoke"), ["yoke"])

    def test_comma_separated_returns_list(self) -> None:
        self.assertEqual(
            parse_project_cli_arg("yoke,externalwebapp"), ["yoke", "externalwebapp"]
        )

    def test_whitespace_around_ids_is_stripped(self) -> None:
        self.assertEqual(
            parse_project_cli_arg("  yoke , externalwebapp  "),
            ["yoke", "externalwebapp"],
        )

    def test_empty_segments_are_dropped(self) -> None:
        self.assertEqual(
            parse_project_cli_arg("yoke,,externalwebapp,"),
            ["yoke", "externalwebapp"],
        )

    def test_only_commas_returns_none(self) -> None:
        self.assertIsNone(parse_project_cli_arg(",,,"))


class TestExportSurface(unittest.TestCase):
    """AC-1: exported callables are present and signatures match contract."""

    def test_module_exports_required_symbols(self) -> None:
        from yoke_core.domain import session_project_scope

        self.assertTrue(
            hasattr(session_project_scope, "resolve_session_project_scope")
        )
        self.assertTrue(
            hasattr(session_project_scope, "parse_project_cli_arg")
        )

    def test_resolve_returns_list_of_int(self) -> None:
        conn = _make_db(["yoke"])
        try:
            result = resolve_session_project_scope(conn, override=None)
            self.assertIsInstance(result, list)
            for item in result:
                self.assertIsInstance(item, int)
        finally:
            conn.close()


class TestBackwardCompatPersistedEnvelope(unittest.TestCase):
    """AC-11: when an existing offer_envelope row lacks the new
    ``project_scope`` key, the session should treat it as all-projects (no
    override). This test exercises the resolver in the "envelope lacked the
    key" code path: with ``override=None``, the resolver returns the full
    registered set."""

    def test_missing_envelope_project_scope_falls_through_to_all_projects(self) -> None:
        conn = _make_db(["yoke", "externalwebapp", "third"])
        try:
            # Simulate the call shape the offer path uses when reading a
            # persisted envelope lacking ``project_scope`` — override is
            # ``None`` (the default), resolver returns the full set.
            self.assertEqual(
                sorted(resolve_session_project_scope(conn, override=None)),
                [1, 2, 3],
            )
        finally:
            conn.close()


class TestEndToEndProjectScope(unittest.TestCase):
    """AC-9, AC-10: end-to-end coverage that the resolved ``project_scope``
    actually drives which items surface on the frontier.

    The test registers a fixture project alongside ``yoke``, seeds one
    runnable item in each, and exercises ``compute_frontier`` directly:

    - AC-9: with the all-projects default (resolver returns both ids), both
      items appear on the frontier.
    - AC-10: with ``override=["yoke"]``, only the yoke item appears.
    """

    FIXTURE_PROJECT = "scope-fixture-alpha"

    def _make_end_to_end_db(self):
        from runtime.api.test_dependency_schema import (
            ITEMS_SCHEMA,
            ITEM_DEPENDENCIES_SCHEMA,
        )

        conn = _make_disposable_db()
        apply_fixture_ddl(conn, PROJECTS_SCHEMA)
        apply_fixture_ddl(conn, ITEMS_SCHEMA)
        apply_fixture_ddl(conn, ITEM_DEPENDENCIES_SCHEMA)
        for pid in ("yoke", self.FIXTURE_PROJECT):
            conn.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix) "
                "VALUES (%s, %s, %s, %s)",
                (_project_id(pid), pid, pid.title(), "YOK"),
            )
        # Seed one runnable item per project. Both items use the same
        # status/type/priority so the only differentiator is the project
        # id; AC-9 then proves the new ``IN`` clause spans the scope.
        for item_id, project_id in (
            (501, "yoke"),
            (502, self.FIXTURE_PROJECT),
        ):
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority,
                    project_id, project_sequence, created_at, updated_at,
                    source, frozen)
                   VALUES (%s, %s, 'issue', 'refined-idea', 'high', %s, %s,
                           '2026-05-21', '2026-05-21', 'user', 0)""",
                (
                    item_id,
                    f"Runnable in {project_id}",
                    _project_id(project_id),
                    item_id,
                ),
            )
        conn.commit()
        return conn

    def test_default_scope_surfaces_items_across_all_projects(self) -> None:
        """AC-9: with no operator override, the resolver returns every
        registered project, and ``compute_frontier`` surfaces items from
        each."""
        from yoke_core.domain.frontier_compute import compute_frontier

        conn = self._make_end_to_end_db()
        try:
            scope = resolve_session_project_scope(conn, override=None)
            self.assertEqual(sorted(scope), sorted([1, _project_id(self.FIXTURE_PROJECT)]))

            result = compute_frontier(conn, project_scope=scope)
            runnable_ids = {fi.item_id for fi in result.runnable}
            self.assertIn("YOK-501", runnable_ids)
            self.assertIn("YOK-502", runnable_ids)
        finally:
            conn.close()

    def test_override_narrows_scope_to_yoke_only(self) -> None:
        """AC-10: ``--project yoke`` narrows the frontier to yoke items
        only — the fixture project's item is excluded."""
        from yoke_core.domain.frontier_compute import compute_frontier

        conn = self._make_end_to_end_db()
        try:
            scope = resolve_session_project_scope(conn, override=["yoke"])
            self.assertEqual(scope, [1])

            result = compute_frontier(conn, project_scope=scope)
            runnable_ids = {fi.item_id for fi in result.runnable}
            self.assertIn("YOK-501", runnable_ids)
            self.assertNotIn("YOK-502", runnable_ids)
        finally:
            conn.close()

    def test_override_can_select_only_the_fixture_project(self) -> None:
        """Symmetric to AC-10: an explicit override naming only the fixture
        project excludes yoke's items."""
        from yoke_core.domain.frontier_compute import compute_frontier

        conn = self._make_end_to_end_db()
        try:
            scope = resolve_session_project_scope(
                conn, override=[self.FIXTURE_PROJECT]
            )
            self.assertEqual(scope, [_project_id(self.FIXTURE_PROJECT)])

            result = compute_frontier(conn, project_scope=scope)
            runnable_ids = {fi.item_id for fi in result.runnable}
            self.assertNotIn("YOK-501", runnable_ids)
            self.assertIn("YOK-502", runnable_ids)
        finally:
            conn.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
