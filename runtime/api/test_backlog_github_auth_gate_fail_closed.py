"""GitHub sync auth probes fail closed unless the project is backlog-only."""

from __future__ import annotations

import io
from collections.abc import Callable
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH, make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_sync


SyncCall = Callable[[object, io.StringIO], int]


@pytest.mark.parametrize(
    ("operation", "invoke"),
    [
        (
            "post-comment",
            lambda conn, err: backlog_github_sync.post_comment(
                "91", "idea", "implementing", conn=conn, stderr=err,
            ),
        ),
        (
            "sync-labels",
            lambda conn, err: backlog_github_sync.sync_labels(
                "91", conn=conn, stderr=err,
            ),
        ),
        (
            "sync-done-item",
            lambda conn, err: backlog_github_sync.sync_done_item(
                "91", "implementing", conn=conn, stderr=err,
            ),
        ),
        (
            "sync-frozen-label",
            lambda conn, err: backlog_github_sync.sync_frozen_label(
                "91", "true", conn=conn, stderr=err,
            ),
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_missing_app_auth_is_nonzero(
    operation: str,
    invoke: SyncCall,
) -> None:
    conn = make_db()
    insert_item(
        conn,
        id=91,
        type="issue",
        status="implementing",
        project="buzz",
        github_issue="#191",
    )
    stderr = io.StringIO()
    try:
        with patch(f"{GH_PATCH}._github_auth_available", return_value=False):
            result = invoke(conn, stderr)
    finally:
        conn.close()

    assert result == 1
    assert operation in stderr.getvalue()
    assert "no usable GitHub App auth" in stderr.getvalue()
