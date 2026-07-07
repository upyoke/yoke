"""GitHub blocked-label sync.

Mirrors the frozen-label flow: ``sync_blocked_label`` should idempotently
create the `blocked` label (color matches BLOCKED_LABEL_COLOR), then add
it when ``items.blocked=1`` and remove it when ``items.blocked=0``. When
the flag clears, the call also scrubs the legacy `status:blocked` label
from the issue so a row repaired by the migration converges on a single
indicator.

Tests mock the typed REST label surfaces directly:
``backlog_github_state_sync._label_rest`` for ``sync_blocked_label``,
``backlog_github_label_sync._rest`` for the full ``sync_labels`` paths.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import (
    backlog_github_label_sync,
    backlog_github_state_sync,
    backlog_github_sync,
)
from yoke_core.domain.backlog_github_fetch import BLOCKED_LABEL_COLOR
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_LABEL_REST_STATE = "yoke_core.domain.backlog_github_state_sync._label_rest"
_LABEL_REST_LABELS = "yoke_core.domain.backlog_github_label_sync._rest"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "buzz")
    return ProjectGithubAuth(
        project=proj, repo="org/buzz", token="ghp_fake",
        env={"GH_TOKEN": "ghp_fake"},
    )


def test_sync_blocked_label_adds_label_when_true():
    db = _make_db()
    insert_item(db, id=30, type="issue", status="implementing",
                project="buzz", github_issue="#50")
    stdout = io.StringIO()

    with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_state_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(f"{_LABEL_REST_STATE}.ensure_label") as ensure, patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ) as add_labels, patch(
        f"{_LABEL_REST_STATE}.remove_label",
    ):
        rc = backlog_github_sync.sync_blocked_label(
            "30", "true", conn=db, stdout=stdout,
        )

    assert rc == 0
    # Label created idempotently with the blocked color.
    ensure.assert_called_once()
    assert ensure.call_args.args[0] == "blocked"
    assert ensure.call_args.args[1] == BLOCKED_LABEL_COLOR
    add_labels.assert_called_once_with(
        "org/buzz", 50, ["blocked"], token="ghp_fake",
    )
    assert "Blocked label added: BUZ-30 → #50" in stdout.getvalue()
    db.close()


def test_sync_blocked_label_removes_label_when_false():
    db = _make_db()
    insert_item(db, id=31, type="issue", status="refined-idea",
                project="buzz", github_issue="#51")
    stdout = io.StringIO()

    with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_state_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(f"{_LABEL_REST_STATE}.ensure_label"), patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ), patch(
        f"{_LABEL_REST_STATE}.remove_label",
    ) as remove_label:
        rc = backlog_github_sync.sync_blocked_label(
            "31", "false", conn=db, stdout=stdout,
        )

    assert rc == 0
    # The clear-path scrubs both `blocked` and the legacy `status:blocked`.
    removed = {call.args[2] for call in remove_label.call_args_list}
    assert "blocked" in removed
    assert "status:blocked" in removed
    db.close()


def test_full_sync_labels_adds_blocked_label_when_flagged():
    db = _make_db()
    insert_item(db, id=34, type="issue", status="implementing",
                project="buzz", github_issue="#54")
    db.execute("UPDATE items SET blocked = 1 WHERE id = 34")
    db.commit()

    with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_label_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(
        f"{_LABEL_REST_LABELS}.fetch_issue_labels",
        return_value=["status:implementing"],
    ), patch(f"{_LABEL_REST_LABELS}.ensure_label"), patch(
        f"{_LABEL_REST_LABELS}.add_labels",
    ) as add_labels, patch(
        f"{_LABEL_REST_LABELS}.remove_label",
    ):
        rc = backlog_github_sync.sync_labels("34", conn=db)

    assert rc == 0
    added = [label for call in add_labels.call_args_list for label in call.args[2]]
    assert "blocked" in added
    db.close()


def test_full_sync_labels_removes_blocked_and_legacy_status_labels_when_unblocked():
    db = _make_db()
    insert_item(db, id=35, type="issue", status="implementing",
                project="buzz", github_issue="#55")

    with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
        f"{GH_PATCH}._validate_issue_in_repo", return_value=True,
    ), patch.object(
        backlog_github_label_sync, "resolve_project_github_auth",
        side_effect=_ok_resolver,
    ), patch(
        f"{_LABEL_REST_LABELS}.fetch_issue_labels",
        return_value=["status:blocked", "blocked"],
    ), patch(f"{_LABEL_REST_LABELS}.ensure_label"), patch(
        f"{_LABEL_REST_LABELS}.add_labels",
    ), patch(
        f"{_LABEL_REST_LABELS}.remove_label",
    ) as remove_label:
        rc = backlog_github_sync.sync_labels("35", conn=db)

    assert rc == 0
    removed = {call.args[2] for call in remove_label.call_args_list}
    assert {"blocked", "status:blocked"} <= removed
    db.close()


def test_sync_blocked_label_dry_run():
    db = _make_db()
    insert_item(db, id=32, type="issue", status="idea",
                project="buzz", github_issue="#52")
    stdout = io.StringIO()

    with patch(f"{GH_PATCH}._dry_run", return_value=True), patch(
        f"{_LABEL_REST_STATE}.ensure_label",
    ) as ensure, patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ) as add, patch(
        f"{_LABEL_REST_STATE}.remove_label",
    ) as remove:
        rc = backlog_github_sync.sync_blocked_label(
            "32", "true", conn=db, stdout=stdout,
        )

    assert rc == 0
    ensure.assert_not_called()
    add.assert_not_called()
    remove.assert_not_called()
    assert "DRY-RUN" in stdout.getvalue()
    assert "blocked=true" in stdout.getvalue()
    db.close()


def test_sync_blocked_label_noop_without_github_issue():
    db = _make_db()
    insert_item(db, id=33, type="issue", status="idea", project="buzz")
    with patch(f"{GH_PATCH}._pat_available", return_value=True), patch(
        f"{_LABEL_REST_STATE}.ensure_label",
    ) as ensure, patch(
        f"{_LABEL_REST_STATE}.add_labels",
    ) as add, patch(
        f"{_LABEL_REST_STATE}.remove_label",
    ) as remove:
        rc = backlog_github_sync.sync_blocked_label("33", "true", conn=db)
    assert rc == 0
    ensure.assert_not_called()
    add.assert_not_called()
    remove.assert_not_called()
    db.close()


def test_blocked_label_color_matches_constant():
    """The label color is exposed through the shim for downstream callers."""
    assert backlog_github_sync.BLOCKED_LABEL_COLOR == BLOCKED_LABEL_COLOR


def test_cli_blocked_label_dispatch():
    from yoke_core.domain.backlog_github_sync_cli import main

    with patch("yoke_core.domain.backlog_github_sync.sync_blocked_label") as mock:
        mock.return_value = 0
        rc = main(["blocked-label", "30", "true"])
    assert rc == 0
    mock.assert_called_once_with("30", "true")
