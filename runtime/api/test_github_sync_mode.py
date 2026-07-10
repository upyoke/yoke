"""Per-project GitHub sync switch: reader, sync-surface gates, flip round-trip.

``projects.github_sync_mode`` is the one authority for whether a project's
backlog mirrors to GitHub issues. These tests cover:

- the column-tolerant reader (absent column / NULL / stored value / bad value);
- the sync helper family skipping (rc 0 + mode-language line) for
  ``backlog_only`` projects without touching the REST surface — including
  the body-sync path that ``items.structured_field.replace`` with
  ``options.sync_github_body=true`` drives;
- the explicit-refusal surface (``migrate_issue_to_repo``);
- the operator flip round-trip through ``cmd_upsert`` / ``cmd_update`` /
  ``cmd_get`` (the ``yoke projects update --github-sync-mode`` /
  ``yoke projects get --field github_sync_mode`` backing calls).

Tests mock the typed REST surfaces; no live GitHub calls are made.
"""

from __future__ import annotations

import io
from unittest import mock

import pytest

from runtime.api.backlog_github_sync_test_helpers import make_db as _make_db
from runtime.api.conftest import insert_item
# Import the umbrella module FIRST so its transitive re-export chain
# completes before any sibling-specific submodule attempts to import it.
from yoke_core.domain import backlog_github_sync  # noqa: I001
from yoke_core.domain import (
    backlog_github_body_title_sync as body_title_sync,
)
from yoke_core.domain.projects_github_sync_mode import (
    GITHUB_SYNC_BACKLOG_ONLY,
    GITHUB_SYNC_ENABLED,
    GithubSyncModeError,
    github_sync_disabled_notice,
    github_sync_enabled,
    resolve_github_sync_mode,
)


def _set_mode(conn, slug: str, mode) -> None:
    conn.execute(
        "UPDATE projects SET github_sync_mode = %s WHERE slug = %s",
        (mode, slug),
    )
    conn.commit()


@pytest.fixture
def db():
    conn = _make_db()
    yield conn
    conn.close()


class TestModeReader:
    def test_null_resolves_enabled(self, db):
        assert resolve_github_sync_mode("yoke", conn=db) == GITHUB_SYNC_ENABLED
        assert github_sync_enabled("yoke", conn=db)

    def test_absent_column_resolves_enabled(self, db):
        db.execute("ALTER TABLE projects DROP COLUMN github_sync_mode")
        db.commit()
        assert resolve_github_sync_mode("yoke", conn=db) == GITHUB_SYNC_ENABLED

    def test_backlog_only_round_trips(self, db):
        _set_mode(db, "yoke", GITHUB_SYNC_BACKLOG_ONLY)
        assert (
            resolve_github_sync_mode("yoke", conn=db)
            == GITHUB_SYNC_BACKLOG_ONLY
        )
        assert not github_sync_enabled("yoke", conn=db)
        # Other projects stay independent.
        assert github_sync_enabled("buzz", conn=db)

    def test_unknown_project_resolves_enabled(self, db):
        assert resolve_github_sync_mode("nope", conn=db) == GITHUB_SYNC_ENABLED

    def test_invalid_stored_value_raises_typed_error(self, db):
        _set_mode(db, "yoke", "sideways")
        with pytest.raises(GithubSyncModeError):
            resolve_github_sync_mode("yoke", conn=db)


class TestSyncSurfacesSkip:
    """Every sync entrypoint short-circuits with rc 0 + the mode line."""

    def test_sync_item_creates_nothing(self, db):
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        insert_item(db, id=71, project="buzz", github_issue=None, spec="Body")
        stdout = io.StringIO()

        with mock.patch(
            "yoke_core.domain.backlog_github_item_create.github_rest.create_issue",
            side_effect=AssertionError("issue created for backlog-only project"),
        ):
            rc = backlog_github_sync.sync_item("71", conn=db, stdout=stdout)

        assert rc == 0
        assert github_sync_disabled_notice("buzz", "sync-item") in stdout.getvalue()
        row = db.execute(
            "SELECT github_issue FROM items WHERE id = 71"
        ).fetchone()
        assert row[0] is None

    def test_sync_body_no_ops_cleanly(self, db):
        """The choke point behind options.sync_github_body=true."""
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        insert_item(db, id=72, project="buzz", github_issue="#80", spec="Body")
        stdout = io.StringIO()

        with mock.patch.object(
            body_title_sync.github_rest, "update_issue",
            side_effect=AssertionError("REST reached for backlog-only project"),
        ):
            rc = backlog_github_sync.sync_body("72", conn=db, stdout=stdout)

        assert rc == 0
        assert github_sync_disabled_notice("buzz", "sync-body") in stdout.getvalue()

    def test_sync_title_skips(self, db):
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        insert_item(db, id=73, project="buzz", github_issue="#81", spec="Body")
        stdout = io.StringIO()

        rc = backlog_github_sync.sync_title("73", conn=db, stdout=stdout)

        assert rc == 0
        assert github_sync_disabled_notice("buzz", "sync-title") in stdout.getvalue()

    def test_post_comment_skips(self, db):
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        insert_item(db, id=74, project="buzz", github_issue="#82", spec="Body")
        stdout = io.StringIO()

        rc = backlog_github_sync.post_comment(
            "74", "idea", "refining-idea", conn=db, stdout=stdout,
        )

        assert rc == 0
        assert (
            github_sync_disabled_notice("buzz", "post-comment")
            in stdout.getvalue()
        )

    def test_close_issue_skips(self, db):
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        insert_item(
            db, id=75, project="buzz", github_issue="#83",
            status="done", spec="Body",
        )
        stdout = io.StringIO()

        rc = backlog_github_sync.close_issue("75", conn=db, stdout=stdout)

        assert rc == 0
        assert (
            github_sync_disabled_notice("buzz", "close-issue")
            in stdout.getvalue()
        )

    def test_enabled_project_still_reaches_github_auth_gate(self, db):
        """Default mode keeps the pre-switch behavior: the GitHub App auth gate runs."""
        insert_item(db, id=76, project="buzz", github_issue="#84", spec="Body")
        stdout, stderr = io.StringIO(), io.StringIO()

        with mock.patch(
            "yoke_core.domain.backlog_github_sync._github_auth_available",
            return_value=False,
        ) as pat:
            rc = backlog_github_sync.sync_body(
                "76", conn=db, stdout=stdout, stderr=stderr,
            )

        assert rc == 1
        pat.assert_called_once_with("buzz")
        assert "no usable GitHub App auth" in stderr.getvalue()


class TestExplicitRefusal:
    def test_migrate_issue_to_backlog_only_target_refuses(self, db):
        _set_mode(db, "buzz", GITHUB_SYNC_BACKLOG_ONLY)
        stderr = io.StringIO()

        rc = backlog_github_sync.migrate_issue_to_repo(
            "42", "9", "org/old", "old", "org/buzz", "buzz",
            conn=db, stdout=io.StringIO(), stderr=stderr,
        )

        assert rc == 1
        assert (
            github_sync_disabled_notice("buzz", "migrate-issue")
            in stderr.getvalue()
        )


@pytest.fixture
def ambient_db(monkeypatch):
    """Disposable Postgres DB pinned as the ambient connect() authority.

    The projects CRUD helpers (``cmd_upsert`` / ``cmd_get`` /
    ``cmd_update``) own their connections, so the flip round-trip tests
    pin the ambient DSN instead of threading a ``conn``.
    """
    from runtime.api.fixtures import pg_testdb
    from runtime.api.fixtures.schema_ddl import apply_fixture_schema
    from yoke_core.domain import db_backend

    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV, pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


class TestStructuredWriteBodySync:
    def test_body_sync_step_reports_success_for_backlog_only(self, ambient_db):
        """``execute_structured_write`` treats the skip as success: its
        ``_sync_body`` step returns ok (no ``sync_warning``) and logs the
        mode line — the ``options.sync_github_body=true`` no-op contract."""
        from runtime.api.fixtures import pg_testdb
        from yoke_core.domain import backlog_rendering

        conn = pg_testdb.connect_test_database(ambient_db)
        try:
            _set_mode(conn, "yoke", GITHUB_SYNC_BACKLOG_ONLY)
            insert_item(
                conn, id=91, project="yoke", github_issue="#90", spec="Body",
            )
        finally:
            conn.close()

        out = io.StringIO()
        ok, _mode = backlog_rendering._sync_body(91, out)

        assert ok is True
        assert github_sync_disabled_notice("yoke", "sync-body") in out.getvalue()


class TestFlipRoundTrip:
    """Backing calls for `yoke projects update --github-sync-mode` and
    `yoke projects get --field github_sync_mode`."""

    def test_upsert_flip_and_field_read(self, ambient_db):
        from yoke_core.domain.projects_crud import cmd_get, cmd_update
        from yoke_core.domain.projects_upsert import cmd_upsert

        result = cmd_upsert(
            slug="buzz", name="Buzz",
            github_sync_mode=GITHUB_SYNC_BACKLOG_ONLY, mode="update",
        )
        assert (
            result["project"]["github_sync_mode"] == GITHUB_SYNC_BACKLOG_ONLY
        )
        assert cmd_get("buzz", "github_sync_mode") == GITHUB_SYNC_BACKLOG_ONLY
        assert not github_sync_enabled("buzz")

        # Flip back through the field-level updater.
        cmd_update("buzz", "github_sync_mode", GITHUB_SYNC_ENABLED)
        assert cmd_get("buzz", "github_sync_mode") == GITHUB_SYNC_ENABLED
        assert github_sync_enabled("buzz")

    def test_upsert_rejects_invalid_mode(self, ambient_db):
        from yoke_core.domain.projects_upsert import cmd_upsert

        with pytest.raises(ValueError):
            cmd_upsert(
                slug="buzz", name="Buzz",
                github_sync_mode="sideways", mode="update",
            )

    def test_field_update_rejects_invalid_mode(self):
        # Validation fires before any DB connection is opened.
        from yoke_core.domain.projects_crud import cmd_update

        with pytest.raises(GithubSyncModeError):
            cmd_update("buzz", "github_sync_mode", "sideways")
