"""A committed terminal transition closes the issue and posts one status comment."""

import io
from unittest.mock import patch
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_post_write_sync, backlog_rendering


class TestPostWriteTerminalAnnouncement:
    def test_terminal_status_closes_silently_then_posts_one_comment(self, test_db):
        insert_item(test_db, id=40, workflow_id="dash", status="done")
        out = io.StringIO()
        with (
            patch.object(
                backlog_rendering,
                "_close_issue",
                return_value=True,
            ) as close_issue,
            patch.object(
                backlog_rendering,
                "_sync_labels",
                return_value=True,
            ),
            patch.object(
                backlog_rendering,
                "_post_comment",
                return_value=True,
            ) as post_comment,
        ):
            rc = backlog_post_write_sync.run_post_db_sync(
                item_id=40,
                field="status",
                value="done",
                old_status="reviewing-implementation",
                out=out,
            )

        assert rc == 0
        close_issue.assert_called_once()
        post_comment.assert_called_once_with(
            40,
            "reviewing-implementation",
            "done",
            out,
        )

    def test_already_terminal_status_posts_no_comment(self, test_db):
        insert_item(test_db, id=40, workflow_id="dash", status="done")
        out = io.StringIO()
        with (
            patch.object(
                backlog_rendering,
                "_close_issue",
                return_value=True,
            ) as close_issue,
            patch.object(
                backlog_rendering,
                "_sync_labels",
                return_value=True,
            ),
            patch.object(
                backlog_rendering,
                "_post_comment",
                return_value=True,
            ) as post_comment,
        ):
            rc = backlog_post_write_sync.run_post_db_sync(
                item_id=40,
                field="status",
                value="done",
                old_status="done",
                out=out,
            )

        assert rc == 0
        close_issue.assert_called_once()
        post_comment.assert_not_called()
