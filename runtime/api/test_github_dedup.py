"""Tests for the shared GitHub dedup helper plus its ``sync_item``
integration. Epic parent/task integration tests live in the sibling
``test_github_dedup_epic.py`` module.

The helper centralizes the typed-REST search pattern used by both
``backlog_github_sync.sync_item`` and the epic parent/task paths in
``epic_task_sync_github``. GitHub's full-text title search is fuzzy on
bracketed and numeric tokens, so a token match is not a guarantee of an
exact bracketed-prefix match — the helper post-filters candidates by
``title.startswith(prefix)`` so wrong-issue reuse cannot occur. Wrong
reuse is worse than creating a duplicate issue.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import ANY, patch

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import (
    backlog_github_sync,
    github_dedup,
    github_rest,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog import seed_test_canonical_actors
from runtime.api.fixtures.schema_ddl import apply_fixture_schema


_DEDUP_PATCH = "yoke_core.domain.github_dedup.github_rest.list_issues"
_CREATE_PATCH = "yoke_core.domain.backlog_github_item_create.github_rest.create_issue"


# Canonical fuzzy-substring repro: a [YOK-1500] search returns issue
# #3543 whose title merely contains "1500" as a substring inside
# "1000-1500 lines" — the helper must reject it.
def _issue(number: int, title: str) -> github_rest.Issue:
    return github_rest.Issue(number=number, title=title, state="OPEN")


def _make_db() -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    apply_fixture_schema(conn)
    seed_test_canonical_actors(conn)
    conn.execute(
        "UPDATE projects SET github_repo = %s WHERE id = %s",
        ("org/externalwebapp", SEED_PROJECT_IDS["externalwebapp"]),
    )
    conn.commit()
    return pg_testdb.drop_database_on_close(conn, name)


# ---------------------------------------------------------------------------
# Unit tests for github_dedup.search_existing_issue
# ---------------------------------------------------------------------------


class TestSearchExistingIssue:
    def test_returns_none_when_rest_fails(self):
        stderr = io.StringIO()
        with patch(
            _DEDUP_PATCH,
            side_effect=github_rest.RestTransportError("boom", status=500),
        ):
            result = github_dedup.search_existing_issue(
                "[YOK-1]", project="externalwebapp", stderr=stderr,
            )
        assert result is None
        assert "Skipping reuse" in stderr.getvalue()

    def test_returns_none_on_empty_results(self):
        with patch(_DEDUP_PATCH, return_value=[]):
            assert github_dedup.search_existing_issue(
                "[YOK-1]", project="externalwebapp",
            ) is None

    def test_rejects_fuzzy_substring_match(self):
        # Search prefix [YOK-1500]; candidate title starts with a different YOK-N.
        fuzzy = _issue(
            3543,
            "[YOK-1498] 350-line decomp: split runtime/api/test_*.py top-14 "
            "(1000-1500 lines)",
        )
        with patch(_DEDUP_PATCH, return_value=[fuzzy]):
            result = github_dedup.search_existing_issue(
                "[YOK-1500]", project="externalwebapp",
            )
        assert result is None

    def test_returns_first_exact_prefix_match(self):
        candidates = [
            _issue(99, "[YOK-2] Other"),
            _issue(200, "[YOK-1] First"),
            _issue(201, "[YOK-1] Second"),
        ]
        with patch(_DEDUP_PATCH, return_value=candidates):
            result = github_dedup.search_existing_issue(
                "[YOK-1]", project="externalwebapp",
            )
        assert result == ("200", "[YOK-1] First")

    def test_requires_issue_number_on_exact_match(self):
        candidates = [
            _issue(0, "[YOK-1] No number"),
            _issue(4, "[YOK-1] Match"),
        ]
        with patch(_DEDUP_PATCH, return_value=candidates):
            result = github_dedup.search_existing_issue(
                "[YOK-1]", project="externalwebapp",
            )
        assert result == ("4", "[YOK-1] Match")


# ---------------------------------------------------------------------------
# Integration: backlog_github_sync.sync_item
# ---------------------------------------------------------------------------


class TestSyncItemDedup:
    def _patch_chain(self, list_return, create_return=None):
        """Common patch chain for sync_item dedup integration tests."""
        return [
            patch("yoke_core.domain.backlog_github_sync._github_auth_available", return_value=True),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(
                "yoke_core.domain.backlog_github_sync_accessor.bgs",
                wraps=lambda: backlog_github_sync,
            ),
            patch(_DEDUP_PATCH, return_value=list_return),
            (patch(_CREATE_PATCH, return_value=create_return) if create_return else None),
            patch("yoke_core.domain.backlog_github_item_create._regenerate_md"),
        ]

    def test_reuses_existing_github_issue_on_exact_prefix(self):
        """AC-4: happy path — exact-prefix candidate IS reused."""
        db = _make_db()
        insert_item(db, id=20, type="issue", status="idea", project="externalwebapp")
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.backlog_github_sync._github_auth_available", return_value=True,
        ), patch(
            "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
            return_value=None,
        ), patch(
            _DEDUP_PATCH,
            return_value=[_issue(777, "[EXT-20] Existing item title")],
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ):
            rc = backlog_github_sync.sync_item("20", conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 20").fetchone()[0]
        assert gh_issue == "#777"
        assert "reusing" in stdout.getvalue()
        db.close()

    def test_reuses_existing_epic_issue_and_syncs_child_tasks(self):
        """AC-4: exact-prefix reuse for epic items also runs child sync."""
        db = _make_db()
        insert_item(db, id=23, type="epic", status="planning", project="externalwebapp")
        insert_epic_task(db, epic_id=23, task_num=1, title="Task 1", status="planned")
        stdout = io.StringIO()

        with patch(
            "yoke_core.domain.backlog_github_sync._github_auth_available", return_value=True,
        ), patch(
            "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
            return_value=None,
        ), patch(
            _DEDUP_PATCH,
            return_value=[_issue(777, "[EXT-23] Existing epic title")],
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_sync.epic_task_sync.sync_epic_tasks",
            return_value=0,
        ) as mock_task_sync:
            rc = backlog_github_sync.sync_item("23", conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 23").fetchone()[0]
        assert gh_issue == "#777"
        mock_task_sync.assert_called_once_with("EXT-23", conn=db, stdout=stdout, stderr=ANY)
        db.close()

    def test_rejects_fuzzy_substring_match(self):
        """AC-3 regression: fuzzy candidate (title contains the new YOK-N as a
        substring) must NOT be reused; a fresh issue is created instead.
        """
        db = _make_db()
        insert_item(db, id=1500, type="issue", status="idea", project="externalwebapp")
        stdout = io.StringIO()

        fuzzy = _issue(
            3543,
            "[YOK-1498] 350-line decomp: split runtime/api/test_*.py top-14 "
            "(1000-1500 lines)",
        )
        created = _issue(3545, "[YOK-1500] New")

        with patch(
            "yoke_core.domain.backlog_github_sync._github_auth_available", return_value=True,
        ), patch(
            "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
            return_value=None,
        ), patch(_DEDUP_PATCH, return_value=[fuzzy]), patch(
            _CREATE_PATCH, return_value=created,
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ):
            rc = backlog_github_sync.sync_item("1500", conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 1500").fetchone()[0]
        assert gh_issue != "#3543"
        assert gh_issue == "#3545"
        assert "reusing" not in stdout.getvalue()
        db.close()

    def test_skips_rest_failure_response(self):
        """AC-6: a REST transport failure during dedup must NOT be reused;
        the helper surfaces a warning and falls through to creation.
        """
        db = _make_db()
        insert_item(db, id=42, type="issue", status="idea", project="externalwebapp")
        stdout = io.StringIO()
        stderr = io.StringIO()
        created = _issue(4242, "[EXT-42] New")

        with patch(
            "yoke_core.domain.backlog_github_sync._github_auth_available", return_value=True,
        ), patch(
            "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
            return_value=None,
        ), patch(
            _DEDUP_PATCH,
            side_effect=github_rest.RestTransportError("boom", status=500),
        ), patch(
            _CREATE_PATCH, return_value=created,
        ), patch(
            "yoke_core.domain.backlog_github_item_create._regenerate_md",
        ), patch(
            "yoke_core.domain.backlog_github_item_create._ensure_label",
        ):
            rc = backlog_github_sync.sync_item("42", conn=db, stdout=stdout, stderr=stderr)

        assert rc == 0
        gh_issue = db.execute("SELECT github_issue FROM items WHERE id = 42").fetchone()[0]
        assert gh_issue == "#4242"
        assert "reusing" not in stdout.getvalue()
        assert "Skipping reuse" in stderr.getvalue()
        db.close()
