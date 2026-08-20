"""GitHub sync auth probes fail closed unless the project is disabled.

The done closeout is not one of the probe-gated operations. It resolves the
authorization it needs itself, before the first mutation, so an auth failure
refuses the whole closeout instead of stopping partway through one.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from unittest.mock import patch

import pytest

from runtime.api.backlog_github_sync_test_helpers import GH_PATCH, make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_done_sync
from yoke_core.domain import backlog_github_sync


SyncCall = Callable[[object, io.StringIO], int]


@pytest.mark.parametrize(
    ("operation", "invoke"),
    [
        (
            "post-comment",
            lambda conn, err: backlog_github_sync.post_comment(
                "91",
                "idea",
                "implementing",
                conn=conn,
                stderr=err,
            ),
        ),
        (
            "sync-labels",
            lambda conn, err: backlog_github_sync.sync_labels(
                "91",
                conn=conn,
                stderr=err,
            ),
        ),
        (
            "sync-frozen-label",
            lambda conn, err: backlog_github_sync.sync_frozen_label(
                "91",
                "true",
                conn=conn,
                stderr=err,
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
        workflow_id="issue",
        status="implementing",
        project="externalwebapp",
        github_issue="#191",
    )
    conn.execute(
        "UPDATE projects SET github_sync_mode = 'enabled' WHERE slug = 'externalwebapp'"
    )
    conn.commit()
    stderr = io.StringIO()
    try:
        with patch(f"{GH_PATCH}._github_auth_available", return_value=False):
            result = invoke(conn, stderr)
    finally:
        conn.close()

    assert result == 1
    assert operation in stderr.getvalue()
    assert "no usable GitHub App auth" in stderr.getvalue()


def test_done_closeout_auth_failure_leaves_the_issue_untouched() -> None:
    """An unresolvable authorization applies nothing to the issue.

    The closeout used to write the issue body first and resolve the
    authorization afterwards, so a failure there left an issue whose body
    said done while the issue itself stayed open and the merge reported only
    a warning. Resolving first is what makes the refusal total.
    """
    conn = make_db()
    insert_item(
        conn,
        id=91,
        workflow_id="issue",
        status="done",
        project="externalwebapp",
        github_issue="#191",
    )
    conn.execute(
        "UPDATE projects SET github_sync_mode = 'enabled' WHERE slug = 'externalwebapp'"
    )
    conn.commit()

    def _unresolvable(*_args, **_kwargs):
        raise RuntimeError("reading the machine GitHub App user authorization failed")

    stderr = io.StringIO()
    try:
        with patch.object(
            backlog_github_done_sync,
            "resolve_project_github_auth",
            _unresolvable,
        ), patch(
            "yoke_core.domain.backlog_github_body_writer.update_issue_body_typed"
        ) as body_write, patch(
            "yoke_core.domain.github_rest.set_issue_state"
        ) as close_issue:
            result = backlog_github_sync.sync_done_item(
                "91", "reviewing-implementation", conn=conn, stderr=stderr,
            )
    finally:
        conn.close()

    assert result == 1
    assert "sync-done-item" in stderr.getvalue()
    assert body_write.call_count == 0
    assert close_issue.call_count == 0
