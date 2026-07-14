"""Tests for fixture items-family schema derivation.

Guards two invariants:

1. ``runtime/api/fixtures/schema_ddl_items._ITEMS_DDL`` is **derived** from
   canonical schema init, not a copy of long-form DDL. The derivation
   exposes the live canonical Yoke DB shape so every column added in
   ``yoke_core.domain.schema_init_*`` flows through to fixture
   consumers automatically.

2. Derivation is lazy: importing the fixture modules performs no database
   work, so imports outside pytest never require a live test cluster.

The companion residue scan — refusing regressions back to copied
long-form ``items`` DDL in the migrated helper family — lives in
``runtime/api/test_schema_fixture_residue.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain.schema_common import (
    _column_is_not_null,
    _get_columns,
    _get_tables,
)
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db():
    """Connection to a fresh, empty disposable Postgres database."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    try:
        yield conn
    finally:
        conn.close()
        pg_testdb.drop_test_database(name)


class TestItemsFamilyDerivation:
    """``_ITEMS_DDL`` mirrors canonical schema init."""

    def test_ddl_creates_full_items_family(self, scratch_db) -> None:
        from runtime.api.fixtures.schema_ddl_items import _ITEMS_DDL

        apply_fixture_ddl(scratch_db, _ITEMS_DDL)
        tables = set(_get_tables(scratch_db))
        for expected in ("items", "item_dependencies", "release_entries"):
            assert expected in tables, f"_ITEMS_DDL missing {expected!r}"

    def test_items_columns_match_canonical(self, scratch_db) -> None:
        """Derived ``items`` columns equal a fresh canonical init's."""
        from runtime.api.fixtures.schema_apply import apply_canonical_schema
        from runtime.api.fixtures.schema_ddl_items import _ITEMS_DDL

        apply_fixture_ddl(scratch_db, _ITEMS_DDL)
        derived_cols = set(_get_columns(scratch_db, "items"))

        # Build a fresh canonical DB the same way the derivation does and
        # compare column sets.
        canonical_name = pg_testdb.create_test_database()
        try:
            canonical = pg_testdb.connect_test_database(canonical_name)
            try:
                apply_canonical_schema(canonical)
                canonical_cols = set(_get_columns(canonical, "items"))
            finally:
                canonical.close()
        finally:
            pg_testdb.drop_test_database(canonical_name)

        assert derived_cols == canonical_cols, (
            "Derived items columns drift from canonical: "
            f"missing={canonical_cols - derived_cols}, "
            f"extra={derived_cols - canonical_cols}"
        )

    def test_items_carries_recent_columns(self, scratch_db) -> None:
        """Recently added columns flow through to the derived DDL."""
        from runtime.api.fixtures.schema_ddl_items import _ITEMS_DDL

        apply_fixture_ddl(scratch_db, _ITEMS_DDL)
        cols = set(_get_columns(scratch_db, "items"))
        # Spot-check columns added by recent migrations / one-shots —
        # if any of these go missing the derivation has regressed.
        for col in (
            "browser_qa_metadata",
            "db_mutation_profile",
            "db_compatibility_attestation",
            "owner",
            "spec",
            "deployment_flow",
            "resolution",
            "resolution_ref",
            "resolution_comment",
        ):
            assert col in cols, f"derived items DDL missing recent column {col!r}"

    def test_relaxed_ddl_drops_constraints(self, scratch_db) -> None:
        """Relaxed variant has same columns, no NOT NULL or CHECK."""
        from runtime.api.fixtures.schema_ddl_items import (
            _ITEMS_DDL,
            _ITEMS_RELAXED_DDL,
        )

        apply_fixture_ddl(scratch_db, _ITEMS_RELAXED_DDL)
        relaxed_cols = set(_get_columns(scratch_db, "items"))
        assert not _column_is_not_null(scratch_db, "items", "created_at")
        # Slim insert that would fail strict NOT NULL on created_at /
        # updated_at — and strict CHECK on the legacy status — must
        # succeed on the relaxed shape.
        scratch_db.execute(
            "INSERT INTO items (id, title, status) "
            "VALUES (1, 'minimal-row', 'legacy-status')"
        )
        scratch_db.commit()

        strict_name = pg_testdb.create_test_database()
        try:
            strict = pg_testdb.connect_test_database(strict_name)
            try:
                apply_fixture_ddl(strict, _ITEMS_DDL)
                strict_cols = set(_get_columns(strict, "items"))
            finally:
                strict.close()
        finally:
            pg_testdb.drop_test_database(strict_name)

        assert strict_cols == relaxed_cols, (
            "Relaxed items columns must mirror strict canonical shape"
        )

    def test_derivation_does_not_repoint_ambient_authority(self) -> None:
        """Derivation uses a disposable scratch DB — no env mutation."""
        from yoke_core.domain import db_backend
        from runtime.api.fixtures import schema_ddl_items

        before = os.environ.get(db_backend.PG_DSN_ENV)
        schema_ddl_items._DERIVED_DDL.clear()
        try:
            assert schema_ddl_items._ITEMS_DDL
        finally:
            after = os.environ.get(db_backend.PG_DSN_ENV)
        assert before == after, (
            f"Derivation must not mutate {db_backend.PG_DSN_ENV} — got "
            f"before={before!r} after={after!r}"
        )

    def test_import_requires_no_live_cluster(self) -> None:
        """Importing the fixture DDL modules never touches a database.

        Runs in a subprocess with every Postgres binding removed, so a
        module-import-time derivation regression fails loudly here
        instead of breaking imports outside pytest.
        """
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("YOKE_PG_DSN", "YOKE_PG_DSN_FILE")
        }
        env["PYTHONPATH"] = os.pathsep.join(
            entry for entry in sys.path if entry
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import runtime.api.fixtures.schema_ddl\n"
                "import runtime.api.fixtures.schema_ddl_items\n",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            "fixture DDL module import required database work: "
            f"{result.stderr}"
        )

    def test_derivation_cached_per_process(self, monkeypatch) -> None:
        """The scratch-DB derivation runs at most once per process."""
        from runtime.api.fixtures import schema_ddl_items

        first = schema_ddl_items._ITEMS_DDL
        monkeypatch.setattr(
            schema_ddl_items,
            "_derive_ddl_variants",
            lambda: pytest.fail("cached derivation re-ran"),
        )
        assert schema_ddl_items._ITEMS_DDL == first
