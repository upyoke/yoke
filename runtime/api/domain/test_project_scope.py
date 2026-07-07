"""Unit tests for ``project_scope.normalize_project_scope``.

The scheduler/frontier scope normalizer must resolve slugs strictly
against the ``projects`` table: a fresh universe seeds no project rows,
so any constant slug-to-id fallback would bind a scope name to whatever
unrelated project happens to hold that id.
"""

from __future__ import annotations

import unittest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.project_scope import normalize_project_scope


PROJECTS_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
);
"""


def _make_db(rows: dict[str, int]):
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name,
    )
    apply_fixture_ddl(conn, PROJECTS_SCHEMA)
    for slug, project_id in rows.items():
        conn.execute(
            "INSERT INTO projects (id, slug, name) VALUES (%s, %s, %s)",
            (project_id, slug, slug.title()),
        )
    conn.commit()
    return conn


class TestNormalizeProjectScope(unittest.TestCase):
    def test_numeric_ids_pass_through_without_lookup(self) -> None:
        conn = _make_db({})
        try:
            self.assertEqual(
                normalize_project_scope(conn, [7, "12"]), [7, 12],
            )
        finally:
            conn.close()

    def test_registered_slug_resolves_to_table_id(self) -> None:
        conn = _make_db({"demo": 41})
        try:
            self.assertEqual(normalize_project_scope(conn, ["demo"]), [41])
        finally:
            conn.close()

    def test_unregistered_slug_raises_lookup_error(self) -> None:
        """No constant fallback: an unknown slug never binds to an id."""
        conn = _make_db({"demo": 41})
        try:
            with self.assertRaises(LookupError):
                normalize_project_scope(conn, ["yoke"])
        finally:
            conn.close()

    def test_slug_never_binds_to_unrelated_first_project(self) -> None:
        """A fresh universe's first onboarded project may take id 1; a scope
        naming a different slug must raise rather than bind to it."""
        conn = _make_db({"first-onboarded": 1})
        try:
            with self.assertRaises(LookupError):
                normalize_project_scope(conn, ["buzz"])
        finally:
            conn.close()

    def test_missing_projects_table_raises_lookup_error(self) -> None:
        name = pg_testdb.create_test_database()
        conn = pg_testdb.drop_database_on_close(
            pg_testdb.connect_test_database(name), name,
        )
        try:
            with self.assertRaises(LookupError):
                normalize_project_scope(conn, ["yoke"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
