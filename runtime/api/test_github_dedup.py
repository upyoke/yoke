"""Exact outgoing content comparison and backlog issue adoption tests."""

from __future__ import annotations

import io

import pytest
from unittest.mock import ANY, patch

from runtime.api.conftest import insert_epic_task, insert_item
from yoke_core.domain import (
    backlog_github_sync,
    github_dedup,
    github_rest,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS
from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.backlog import seed_test_canonical_human
from yoke_core.domain.render_body import build_body


_DEDUP_PATCH = "yoke_core.domain.github_dedup.github_rest.list_issues"
_CREATE_PATCH = "yoke_core.domain.backlog_github_item_create.github_rest.create_issue"


# Canonical fuzzy-substring repro: a [YOK-1500] search returns issue
# #3543 whose title merely contains "1500" as a substring inside
# "1000-1500 lines" — the helper must reject it.
def _issue(number: int, title: str, body: str = "") -> github_rest.Issue:
    return github_rest.Issue(number=number, title=title, state="OPEN", body=body)


@pytest.fixture
def dedup_db():
    with pg_testdb.test_database() as conn:
        seed_test_canonical_human(conn)
        conn.execute(
            "UPDATE projects SET github_repo = %s, github_sync_mode = %s WHERE id = %s",
            ("org/externalwebapp", "enabled", SEED_PROJECT_IDS["externalwebapp"]),
        )
        conn.commit()
        yield conn


# ---------------------------------------------------------------------------
# Unit tests for github_dedup.search_existing_issue
# ---------------------------------------------------------------------------


class TestSearchExistingIssue:
    @pytest.mark.parametrize(
        "candidate_title,candidate_body,matched",
        [
            ("[TEST-1] Same", "Body", True),
            (" [TEST-1]  Same ", " Body\n\t", True),
            ("[TEST-1] Same suffix", "Body", False),
            ("[TEST-1] Other", "Body", False),
            ("[TEST-1] Same", "Other body", False),
            ("[TEST-1] Same", "", False),
        ],
        ids=[
            "exact-match",
            "whitespace-normalized-match",
            "title-suffix",
            "other-title",
            "other-body",
            "empty-body",
        ],
    )
    def test_requires_full_title_and_body(
        self, candidate_title, candidate_body, matched
    ):
        with patch(
            _DEDUP_PATCH, return_value=[_issue(7, candidate_title, candidate_body)]
        ):
            result = github_dedup.search_existing_issue(
                "[TEST-1] Same", "Body", project="externalwebapp"
            )
        assert (result is not None) == matched

    def test_skips_mismatches_before_exact_match(self):
        candidates = [
            _issue(4, "[TEST-1] Same", "Old"),
            _issue(5, "[TEST-1] Same", "Body"),
        ]
        with patch(_DEDUP_PATCH, return_value=candidates):
            assert (
                github_dedup.search_existing_issue(
                    "[TEST-1] Same", "Body", project="externalwebapp"
                )[0]
                == "5"
            )

    def test_returns_none_when_rest_fails(self):
        stderr = io.StringIO()
        with patch(
            _DEDUP_PATCH, side_effect=github_rest.RestTransportError("boom", status=500)
        ):
            assert (
                github_dedup.search_existing_issue(
                    "[TEST-1] Same", "Body", project="externalwebapp", stderr=stderr
                )
                is None
            )
        assert "github_dedup_search_failed" in stderr.getvalue()
        assert "Skipping reuse" in stderr.getvalue()


# ---------------------------------------------------------------------------
# Integration: backlog_github_sync.sync_item
# ---------------------------------------------------------------------------


class TestSyncItemDedup:
    def _patch_chain(self, list_return, create_return=None):
        """Common patch chain for sync_item dedup integration tests."""
        return [
            patch(
                "yoke_core.domain.backlog_github_sync._github_auth_available",
                return_value=True,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(
                "yoke_core.domain.backlog_github_sync_accessor.bgs",
                wraps=lambda: backlog_github_sync,
            ),
            patch(_DEDUP_PATCH, return_value=list_return),
            (
                patch(_CREATE_PATCH, return_value=create_return)
                if create_return
                else None
            ),
            patch("yoke_core.domain.backlog_github_item_create._regenerate_md"),
        ]

    def test_reuses_existing_github_issue_on_full_match(self, dedup_db):
        """Only the complete rendered title and body are reused."""
        db = dedup_db
        insert_item(
            db,
            id=20,
            title="Existing item title",
            workflow_id="issue",
            status="idea",
            project="externalwebapp",
        )
        stdout = io.StringIO()

        with (
            patch(
                "yoke_core.domain.backlog_github_sync._github_auth_available",
                return_value=True,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(
                _DEDUP_PATCH,
                return_value=[
                    _issue(777, "[EXT-20] Existing item title", build_body(db, 20))
                ],
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._regenerate_md",
            ),
        ):
            rc = backlog_github_sync.sync_item(20, conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute(
            "SELECT github_issue FROM items WHERE id = 20"
        ).fetchone()[0]
        assert gh_issue == "#777"
        assert "reusing" in stdout.getvalue()

    def test_reuses_existing_epic_issue_and_syncs_child_tasks(self, dedup_db):
        """Full-content reuse for epic items also runs child sync."""
        db = dedup_db
        insert_item(
            db,
            id=23,
            title="Existing epic title",
            workflow_id="epic",
            status="planning",
            project="externalwebapp",
        )
        insert_epic_task(db, epic_id=23, task_num=1, title="Task 1", status="planned")
        stdout = io.StringIO()

        with (
            patch(
                "yoke_core.domain.backlog_github_sync._github_auth_available",
                return_value=True,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(
                _DEDUP_PATCH,
                return_value=[
                    _issue(777, "[EXT-23] Existing epic title", build_body(db, 23))
                ],
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._regenerate_md",
            ),
            patch(
                "yoke_core.domain.backlog_github_sync.epic_task_sync.sync_epic_tasks",
                return_value=0,
            ) as mock_task_sync,
        ):
            rc = backlog_github_sync.sync_item(23, conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute(
            "SELECT github_issue FROM items WHERE id = 23"
        ).fetchone()[0]
        assert gh_issue == "#777"
        mock_task_sync.assert_called_once_with(
            "EXT-23", conn=db, stdout=stdout, stderr=ANY
        )

    def test_rejects_fuzzy_substring_match(self, dedup_db):
        """Regression: fuzzy candidate (title contains the new YOK-N as a
        substring) must NOT be reused; a fresh issue is created instead.
        """
        db = dedup_db
        insert_item(
            db, id=1500, workflow_id="issue", status="idea", project="externalwebapp"
        )
        stdout = io.StringIO()

        fuzzy = _issue(
            3543,
            "[YOK-1498] 350-line decomp: split runtime/api/test_*.py top-14 "
            "(1000-1500 lines)",
        )
        created = _issue(3545, "[YOK-1500] New")

        with (
            patch(
                "yoke_core.domain.backlog_github_sync._github_auth_available",
                return_value=True,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(_DEDUP_PATCH, return_value=[fuzzy]),
            patch(
                _CREATE_PATCH,
                return_value=created,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._regenerate_md",
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._ensure_label",
            ),
        ):
            rc = backlog_github_sync.sync_item(1500, conn=db, stdout=stdout)

        assert rc == 0
        gh_issue = db.execute(
            "SELECT github_issue FROM items WHERE id = 1500"
        ).fetchone()[0]
        assert gh_issue != "#3543"
        assert gh_issue == "#3545"
        assert "reusing" not in stdout.getvalue()

    def test_skips_rest_failure_response(self, dedup_db):
        """A REST transport failure during dedup must NOT be reused;
        the helper surfaces a warning and falls through to creation.
        """
        db = dedup_db
        insert_item(
            db, id=42, workflow_id="issue", status="idea", project="externalwebapp"
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        created = _issue(4242, "[EXT-42] New")

        with (
            patch(
                "yoke_core.domain.backlog_github_sync._github_auth_available",
                return_value=True,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create.resolve_project_github_auth",
                return_value=None,
            ),
            patch(
                _DEDUP_PATCH,
                side_effect=github_rest.RestTransportError("boom", status=500),
            ),
            patch(
                _CREATE_PATCH,
                return_value=created,
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._regenerate_md",
            ),
            patch(
                "yoke_core.domain.backlog_github_item_create._ensure_label",
            ),
        ):
            rc = backlog_github_sync.sync_item(
                42, conn=db, stdout=stdout, stderr=stderr
            )

        assert rc == 0
        gh_issue = db.execute(
            "SELECT github_issue FROM items WHERE id = 42"
        ).fetchone()[0]
        assert gh_issue == "#4242"
        assert "reusing" not in stdout.getvalue()
        assert "Skipping reuse" in stderr.getvalue()
