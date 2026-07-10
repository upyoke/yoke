"""CLI ``main`` dispatch coverage and ``_item_*`` helper tests."""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import (
    GH_PATCH,
    make_db as _make_db,
)
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_label_sync, backlog_github_sync
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_LABEL_REST = "yoke_core.domain.backlog_github_label_sync._rest"


def _ok_resolver(*args, **kwargs):
    proj = kwargs.get("project") or (args[0] if args else "yoke")
    return ProjectGithubAuth(
        project=proj, repo="upyoke/yoke", token="ghs_fake",
    )


# ---------------------------------------------------------------------------
# CLI entrypoint (main)
# ---------------------------------------------------------------------------


class TestMain:
    def test_update_repo_labels_dispatch(self):
        with patch(f"{GH_PATCH}.update_repo_labels", return_value=0) as mock:
            rc = backlog_github_sync.main(["update-repo-labels"])
        assert rc == 0
        mock.assert_called_once_with()

    def test_update_repo_labels_dispatch_dry_run(self):
        with patch(f"{GH_PATCH}.update_repo_labels", return_value=0) as mock:
            rc = backlog_github_sync.main(["update-repo-labels", "--dry-run"])
        assert rc == 0
        mock.assert_called_once_with(dry_run=True)

    def test_sync_labels_dispatch(self):
        with patch(f"{GH_PATCH}.sync_labels", return_value=0) as mock:
            rc = backlog_github_sync.main(["sync-labels", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_sync_item_dispatch(self):
        with patch(f"{GH_PATCH}.sync_item", return_value=0) as mock:
            rc = backlog_github_sync.main(["sync-item", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_post_comment_dispatch(self):
        with patch(f"{GH_PATCH}.post_comment", return_value=0) as mock:
            rc = backlog_github_sync.main(["post-comment", "42", "idea", "implementing"])
        assert rc == 0
        mock.assert_called_once_with("42", "idea", "implementing")

    def test_close_issue_dispatch(self):
        with patch(f"{GH_PATCH}.close_issue", return_value=0) as mock:
            rc = backlog_github_sync.main(["close-issue", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_reopen_issue_dispatch(self):
        with patch(f"{GH_PATCH}.reopen_issue", return_value=0) as mock:
            rc = backlog_github_sync.main(["reopen-issue", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_sync_body_dispatch(self):
        with patch(f"{GH_PATCH}.sync_body", return_value=0) as mock:
            rc = backlog_github_sync.main(["sync-body", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_sync_title_dispatch(self):
        with patch(f"{GH_PATCH}.sync_title", return_value=0) as mock:
            rc = backlog_github_sync.main(["sync-title", "42"])
        assert rc == 0
        mock.assert_called_once_with("42")

    def test_frozen_label_dispatch(self):
        with patch(f"{GH_PATCH}.sync_frozen_label", return_value=0) as mock:
            rc = backlog_github_sync.main(["frozen-label", "42", "true"])
        assert rc == 0
        mock.assert_called_once_with("42", "true")

    def test_unknown_mode_returns_error(self):
        rc = backlog_github_sync.main(["bogus-mode"])
        assert rc == 1

    def test_no_args_returns_error(self):
        rc = backlog_github_sync.main([])
        assert rc == 1


# ---------------------------------------------------------------------------
# _item_context / _item_fields helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_item_context_with_project_repo(self):
        db = _make_db()
        insert_item(db, id=80, type="issue", status="idea", project="buzz", github_issue="#100")
        result = backlog_github_sync._item_context("80", conn=db)
        assert result == ("#100", "buzz", "org/buzz")
        db.close()

    def test_item_context_without_project(self):
        db = _make_db()
        insert_item(db, id=80, type="issue", status="idea", project="yoke", github_issue="#100")
        result = backlog_github_sync._item_context("80", conn=db)
        assert result is not None
        assert result[0] == "#100"
        assert result[1] == "yoke"
        db.close()

    def test_item_context_missing_item(self):
        db = _make_db()
        result = backlog_github_sync._item_context("9999", conn=db)
        assert result is None
        db.close()

    def test_item_fields(self):
        db = _make_db()
        insert_item(db, id=80, type="issue", status="idea", priority="high", project="buzz", title="Test")
        result = backlog_github_sync._item_fields("80", ["title", "status", "priority"], conn=db)
        assert result == {"title": "Test", "status": "idea", "priority": "high"}
        db.close()

    def test_status_display_label(self):
        assert backlog_github_sync._status_display_label("refining-idea") == "refining-idea"
        assert backlog_github_sync._status_display_label("implementing") == "implementing"
        assert backlog_github_sync._status_display_label("reviewed-implementation") == "reviewed-implementation"

    def test_update_repo_labels_dry_run(self):
        stdout = io.StringIO()
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch.object(
            backlog_github_label_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._repo_labels", return_value={}), patch(
            f"{_LABEL_REST}.ensure_label",
        ) as ensure_label:
            rc = backlog_github_sync.update_repo_labels(dry_run=True, stdout=stdout)
        assert rc == 0
        assert "[DRY-RUN] Would create: type:epic" in stdout.getvalue()
        ensure_label.assert_not_called()

    def test_update_repo_labels_updates_changed_color(self):
        stdout = io.StringIO()
        from yoke_core.domain import project_label_policy

        expected = project_label_policy.get_color("label_color_type_epic", "5319E7")
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch.object(
            backlog_github_label_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._repo_labels", return_value={"type:epic": "ffffff"}), patch(
            f"{_LABEL_REST}.ensure_label",
        ) as ensure_label:
            rc = backlog_github_sync.update_repo_labels(stdout=stdout)
        assert rc == 0
        assert f"Updated: type:epic (ffffff -> {expected})" in stdout.getvalue()
        # ensure_label is called once per label-definition; verify the
        # type:epic update happened with the desired color.
        calls = [c for c in ensure_label.call_args_list if c.args[0] == "type:epic"]
        assert calls, "expected ensure_label call for type:epic"
        assert calls[0].args[1] == expected

    def test_update_repo_labels_fetch_failure(self):
        stderr = io.StringIO()
        with patch(f"{GH_PATCH}._github_auth_available", return_value=True), patch.object(
            backlog_github_label_sync, "resolve_project_github_auth",
            side_effect=_ok_resolver,
        ), patch(f"{GH_PATCH}._repo_labels", side_effect=RuntimeError("boom")):
            rc = backlog_github_sync.update_repo_labels(stderr=stderr)
        assert rc == 1
        assert "boom" in stderr.getvalue()


def test_module_help_exits_cleanly_under_m_execution():
    """Regression: ``python3 -m yoke_core.domain.backlog_github_sync --help``
    re-enters the partially-loaded sync siblings under ``__main__`` because
    each one previously imported ``backlog_github_sync as _bgs`` at module
    top. The lazy accessor pattern in every sibling breaks the cycle.
    Asserts both the CLI exit code and that the usage banner reached stdout.
    """
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.backlog_github_sync", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"--help exited {result.returncode}\nSTDERR:\n{result.stderr}"
    assert "Modes:" in result.stdout
    assert "ImportError" not in (result.stderr or "")
