"""Coverage for ``migrate_issue_to_repo`` — cross-repo issue migration.

Tests mock the typed REST surface directly:
``yoke_core.domain.backlog_github_repo_migration.github_rest.*``.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_sync, github_rest
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_REPO_MIG = "yoke_core.domain.backlog_github_repo_migration.github_rest"
_AUTH = (
    "yoke_core.domain.backlog_github_repo_migration."
    "resolve_project_github_auth"
)


def _resolve_auth(project: str, **_kwargs) -> ProjectGithubAuth:
    repos = {
        "archive": "org/archive",
        "externalwebapp": "org/externalwebapp",
        "yoke": "org/yoke",
    }
    return ProjectGithubAuth(
        project=project,
        repo=repos[project],
        token=f"token-{project}",
    )


def _source_issue(
    number: int,
    *,
    state: str = "OPEN",
    title: str = "Issue title",
    body: str = "Issue body content",
    labels: tuple[str, ...] = (),
) -> github_rest.Issue:
    return github_rest.Issue(
        number=number, title=title, state=state, body=body, labels=labels,
        html_url=f"https://github.com/org/yoke/issues/{number}",
    )


def _created_issue(number: int) -> github_rest.Issue:
    return github_rest.Issue(
        number=number, title="created", state="OPEN",
        html_url=f"https://github.com/org/externalwebapp/issues/{number}",
    )


class TestMigrateIssueToRepo:
    def test_successful_migration(self):
        db = _make_db()
        insert_item(
            db, id=90, type="issue", status="idea",
            project="yoke", github_issue="#200",
        )
        stdout = io.StringIO()

        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue",
            return_value=_source_issue(
                200, title="[YOK-90] My issue title", body="Issue body content",
                labels=("status:idea", "priority:high"),
            ),
        ) as get_issue, patch(
            f"{_REPO_MIG}.create_issue", return_value=_created_issue(555),
        ) as create, patch(
            f"{_REPO_MIG}.list_comments", return_value=[],
        ) as list_comments, patch(
            f"{_REPO_MIG}.post_comment",
        ) as post_comment, patch(
            f"{_REPO_MIG}.set_issue_state",
        ) as set_state, patch(
            f"{_REPO_MIG}.delete_issue",
        ) as delete_issue, patch("yoke_core.domain.events.emit_event"):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "90", "200", "org/archive", "archive", "org/externalwebapp", "externalwebapp",
                conn=db, stdout=stdout,
            )

        assert rc == 0
        output = stdout.getvalue()
        assert "[migrate] Created #555 in org/externalwebapp" in output
        assert "[migrate] Updated DB: YOK-90 github_issue = #555" in output
        assert "[migrate] Deleted #200 from org/archive" in output
        assert "[migrate] YOK-90: migration complete" in output

        gh_issue = db.execute(
            "SELECT github_issue FROM items WHERE id = 90"
        ).fetchone()[0]
        assert gh_issue == "#555"

        create.assert_called_once()
        assert create.call_args.kwargs["project"] == "externalwebapp"
        assert get_issue.call_args.kwargs["project"] == "archive"
        assert list_comments.call_args.kwargs["project"] == "archive"
        # Source open → new state stays open (no close-after-create call);
        # only the close-source step closes the source issue.
        close_calls = [
            c for c in set_state.call_args_list
            if c.kwargs.get("state") == "closed"
        ]
        assert len(close_calls) == 1
        assert close_calls[0].kwargs["project"] == "archive"
        delete_issue.assert_called_once()
        assert delete_issue.call_args.kwargs["project"] == "archive"
        # Forward comment on source.
        assert any(
            c.kwargs.get("project") == "archive" and "Migrated to" in c.kwargs.get("body", "")
            for c in post_comment.call_args_list
        )
        db.close()

    def test_migration_with_comments(self):
        db = _make_db()
        insert_item(
            db, id=91, type="issue", status="idea",
            project="yoke", github_issue="#201",
        )
        stdout = io.StringIO()

        comments = [
            github_rest.Comment(id=1, body="First comment", user_login="alice"),
            github_rest.Comment(id=2, body="Second comment", user_login="bob"),
        ]

        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue", return_value=_source_issue(201),
        ), patch(
            f"{_REPO_MIG}.create_issue", return_value=_created_issue(556),
        ), patch(
            f"{_REPO_MIG}.list_comments", return_value=comments,
        ), patch(
            f"{_REPO_MIG}.post_comment",
        ), patch(
            f"{_REPO_MIG}.set_issue_state",
        ), patch(
            f"{_REPO_MIG}.delete_issue",
        ), patch("yoke_core.domain.events.emit_event"):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "91", "201", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
                conn=db, stdout=stdout,
            )

        assert rc == 0
        assert "[migrate] Copied 2 comment(s)" in stdout.getvalue()
        db.close()

    def test_migration_closed_issue_matches_state(self):
        db = _make_db()
        insert_item(
            db, id=92, type="issue", status="done",
            project="yoke", github_issue="#202",
        )
        stdout = io.StringIO()

        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue",
            return_value=_source_issue(202, state="CLOSED"),
        ), patch(
            f"{_REPO_MIG}.create_issue", return_value=_created_issue(557),
        ), patch(
            f"{_REPO_MIG}.list_comments", return_value=[],
        ), patch(
            f"{_REPO_MIG}.post_comment",
        ), patch(
            f"{_REPO_MIG}.set_issue_state",
        ) as set_state, patch(
            f"{_REPO_MIG}.delete_issue",
        ), patch("yoke_core.domain.events.emit_event"):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "92", "202", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
                conn=db, stdout=stdout,
            )

        assert rc == 0
        assert "[migrate] Closed #557 (matching source state)" in stdout.getvalue()
        # Two set_issue_state(state="closed") calls: one for new, one for source.
        close_calls = [
            c for c in set_state.call_args_list
            if c.kwargs.get("state") == "closed"
        ]
        assert len(close_calls) == 2
        db.close()

    def test_dry_run_skips(self):
        stdout = io.StringIO()
        with patch.object(backlog_github_sync, "_dry_run", return_value=True):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "99", "300", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
                stdout=stdout,
            )
        assert rc == 0
        assert "DRY-RUN" in stdout.getvalue()

    def test_fetch_title_failure_returns_error(self):
        stderr = io.StringIO()
        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue",
            side_effect=github_rest.RestTransportError("boom", status=500),
        ):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "99", "300", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
                stderr=stderr,
            )
        assert rc == 1
        assert "could not fetch" in stderr.getvalue()

    def test_create_failure_returns_error(self):
        stderr = io.StringIO()
        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue", return_value=_source_issue(300),
        ), patch(
            f"{_REPO_MIG}.create_issue",
            side_effect=github_rest.RestTransportError("permission denied", status=403),
        ):
            rc = backlog_github_sync.migrate_issue_to_repo(
                "99", "300", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
                stderr=stderr,
            )
        assert rc == 1
        assert "failed to create issue" in stderr.getvalue()

    def test_cli_dispatch(self):
        with patch(f"{GH_PATCH}.migrate_issue_to_repo", return_value=0) as mock:
            rc = backlog_github_sync.main(
                [
                    "migrate-issue", "42", "100", "org/yoke", "yoke",
                    "org/externalwebapp", "externalwebapp",
                ]
            )
        assert rc == 0
        mock.assert_called_once_with(
            "42", "100", "org/yoke", "yoke", "org/externalwebapp", "externalwebapp",
        )

    def test_repo_projection_mismatch_fails_before_github_io(self):
        stderr = io.StringIO()
        with patch(_AUTH, side_effect=_resolve_auth), patch(
            f"{_REPO_MIG}.get_issue",
        ) as get_issue:
            rc = backlog_github_sync.migrate_issue_to_repo(
                "99", "300", "org/stale", "yoke", "org/externalwebapp", "externalwebapp",
                stderr=stderr,
            )

        assert rc == 1
        assert "does not match the verified binding" in stderr.getvalue()
        get_issue.assert_not_called()
