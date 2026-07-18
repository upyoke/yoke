"""Resync engine: repair-mode tests.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module).

GitHub auth: tests below mock the canonical resolver
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
via the autouse ``_auth_resolver`` fixture so repair helpers calling
``_call_domain_sync`` (which now invokes the resolver directly) do not require
real ``project_capabilities`` rows.
"""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from unittest import mock

import pytest

import yoke_core.engines.resync as resync_mod
from yoke_core.engines.resync import DriftRecord, PairedItem
from yoke_core.domain.project_github_auth import ProjectGithubAuth

from yoke_core.engines._resync_test_helpers import (
    populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)


def _fake_auth(token: str = "test-token", project: str = "yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project,
        repo=f"org/{project}",
        token=token,
    )


@pytest.fixture(autouse=True)
def _auth_resolver():
    """Stub the canonical resolver so ``_call_domain_sync`` and
    ``_repair_local_orphan_backlog`` succeed in unit tests.

    Runtime and repair helpers resolve once before invoking domain sync helpers.
    """
    def resolver(project, **_):
        return _fake_auth(project=project or "yoke")

    with mock.patch(
        "yoke_core.engines.resync_runtime.resolve_project_github_auth",
        side_effect=resolver,
    ), mock.patch(
        "yoke_core.engines.resync_repair.resolve_project_github_auth",
        side_effect=resolver,
    ):
        yield


class TestRepairHelpers:
    def test_repair_local_orphan_backlog_success_created(self):
        """sync_item creates a new issue → (True, False, None)."""
        def fake_sync_item(num, **kwargs):
            # Created-fresh path emits no reuse marker.
            print(f"Created issue for YOK-{num}", file=kwargs.get("stdout"))
            return 0

        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=fake_sync_item,
        ) as sync_item:
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999", "yoke",
            )
        sync_item.assert_called_once()
        assert ok is True
        assert reused is False
        assert issue_num is None

    def test_repair_local_orphan_backlog_success_reused(self):
        """sync_item matches an existing issue by title → (True, True, '321')."""
        def fake_sync_item(num, **kwargs):
            out = kwargs.get("stdout")
            print(f"Found existing GitHub issue #321 for YOK-{num} — reusing", file=out)
            print(f"Synced: YOK-{num} → GitHub issue #321 (reused)", file=out)
            return 0

        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=fake_sync_item,
        ):
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999", "yoke",
            )
        assert ok is True
        assert reused is True
        assert issue_num == "321"

    def test_repair_local_orphan_backlog_handles_exception(self):
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_item",
            side_effect=RuntimeError("boom"),
        ):
            ok, reused, issue_num = resync_mod._repair_local_orphan_backlog(
                "YOK-9999", "yoke",
            )
        assert ok is False
        assert reused is False
        assert issue_num is None

    def test_repair_local_orphan_epic_task_rejects_bad_id(self, populated_db):
        assert resync_mod._repair_local_orphan_epic_task("bad-id", "yoke", populated_db) is False

    def test_repair_local_orphan_epic_task_returns_false_when_task_missing(self, test_db):
        assert (
            resync_mod._repair_local_orphan_epic_task(
                "1246/task-999",
                "yoke",
                test_db,
            )
            is False
        )

    def test_repair_local_orphan_epic_task_dry_run_short_circuits(self, populated_db):
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=True):
            assert (
                resync_mod._repair_local_orphan_epic_task(
                    "1246/task-001",
                    "yoke",
                    populated_db,
                )
                is True
            )

    def test_repair_local_orphan_epic_task_success_updates_db_and_closes_terminal_issue(self, populated_db):
        from yoke_core.domain.github_rest import Issue
        from runtime.api.fixtures.file_test_db import connect_test_db

        conn = connect_test_db(populated_db)
        conn.execute("UPDATE epic_tasks SET status='done', body='' WHERE epic_id='1246' AND task_num=1")
        conn.commit()
        conn.close()

        created = Issue(number=321, title="t", state="OPEN")
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
            return_value=created,
        ) as create_issue_mock, mock.patch(
            "yoke_core.engines.resync_repair_epic_task_issue.github_rest.set_issue_state",
            return_value=Issue(number=321, title="t", state="CLOSED"),
        ) as close_mock, mock.patch(
            "yoke_core.engines.resync.task_update_field"
        ) as update_field:
            ok = resync_mod._repair_local_orphan_epic_task(
                "1246/task-001",
                "externalwebapp",
                populated_db,
            )

        assert ok is True
        update_field.assert_called_once()
        assert update_field.call_args.args[1:] == ("1246", 1, "github_issue", "#321")
        assert create_issue_mock.call_args.kwargs["project"] == "externalwebapp"
        assert close_mock.call_args.kwargs == {"project": "externalwebapp", "number": 321, "state": "closed"}

    def test_repair_local_orphan_epic_task_returns_false_when_issue_create_fails(self, populated_db):
        from yoke_core.domain.gh_rest_transport import RestServerError
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
            side_effect=RestServerError("HTTP 502: bad gateway", status=502),
        ):
            ok = resync_mod._repair_local_orphan_epic_task(
                "1246/task-001",
                "yoke",
                populated_db,
            )
        assert ok is False

    def test_repair_local_orphan_epic_task_returns_false_when_issue_number_missing(self, populated_db):
        from yoke_core.domain.github_rest import Issue
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair_epic_task_issue.github_rest.create_issue",
            return_value=Issue(number=0, title="t", state="OPEN"),
        ):
            ok = resync_mod._repair_local_orphan_epic_task(
                "1246/task-001",
                "yoke",
                populated_db,
            )
        assert ok is False


class TestRepairDrift:
    def test_title_drift_backlog_edits_issue(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord("YOK-42", "title", "Correct title", "Wrong title")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair.github_rest.update_issue",
            return_value=Issue(number=100, title="[YOK-42] Correct title", state="OPEN"),
        ) as update_issue:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs == {
            "project": "yoke", "number": 100, "title": "[YOK-42] Correct title",
        }

    def test_title_drift_epic_task_uses_parent_prefix(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord("1246/task-001", "title", "Task one fixed", "Wrong")
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair.github_rest.update_issue",
            return_value=Issue(number=200, title="x", state="OPEN"),
        ) as update_issue:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs["title"] == "[YOK-1246] 001 Task one fixed"
        assert update_issue.call_args.kwargs["number"] == 200

    def test_body_drift_backlog_uses_domain_sync(self, populated_db):
        drift = DriftRecord("YOK-42", "body", "<local>", "<github>")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "externalwebapp", "")]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_body",
            return_value=0,
        ) as sync_body:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync_body.assert_called_once()
        assert sync_body.call_args.args == ("42",)

    def test_body_drift_epic_task_uses_python_sync(self, populated_db):
        drift = DriftRecord("1246/task-001", "body", "<local>", "<github>")
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "yoke", "")]
        with mock.patch("yoke_core.engines.resync.epic_task_sync.sync_task_body", return_value=0) as sync:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync.assert_called_once()
        assert sync.call_args.args == ("1246", 1)

    def test_label_drift_backlog_uses_domain_sync(self, populated_db):
        drift = DriftRecord("YOK-42", "label-status", "status:done", "status:implementing")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_labels",
            return_value=0,
        ) as sync_labels:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync_labels.assert_called_once()
        assert sync_labels.call_args.args == ("42",)

    def test_label_owner_drift_routes_through_sync_labels(self, populated_db):
        """Slice 7: ``label-owner`` drift uses the same `sync_labels`
        sibling that owns ``label-source``. The repair branch must
        recognise the new field name or owner drift would silently
        fall through to the no-op default."""
        drift = DriftRecord("YOK-42", "label-owner", "owner:ben", "owner:yoke-core")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_labels",
            return_value=0,
        ) as sync_labels:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync_labels.assert_called_once()
        assert sync_labels.call_args.args == ("42",)

    def test_label_frozen_dry_run_returns_true(self, populated_db):
        drift = DriftRecord("YOK-42", "label-frozen", "frozen:true", "frozen:absent")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=True):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

    def test_state_drift_backlog_uses_domain_close(self, populated_db):
        drift = DriftRecord("YOK-42", "state", "CLOSED", "OPEN")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.close_issue",
            return_value=0,
        ) as close_issue:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        close_issue.assert_called_once()
        assert close_issue.call_args.args == ("42",)

    def test_state_drift_epic_task_uses_issue_close(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord("1246/task-001", "state", "CLOSED", "OPEN")
        paired = [PairedItem("1246/task-001", "epic_tasks:1246/1", 200, "epic_task", "externalwebapp", "org/externalwebapp")]
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False), mock.patch(
            "yoke_core.engines.resync_repair.github_rest.set_issue_state",
            return_value=Issue(number=200, title="x", state="CLOSED"),
        ) as set_state:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        assert set_state.call_args.kwargs == {
            "project": "externalwebapp", "number": 200, "state": "closed",
        }

    def test_comment_drift_backlog_posts_via_domain_sync(self, populated_db):
        drift = DriftRecord("YOK-42", "comment", "has-status-comment", "missing")
        paired = [PairedItem("YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "")]
        with mock.patch(
            "yoke_core.engines.resync._query_item_status", return_value="done"
        ), mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.post_comment",
            return_value=0,
        ) as post_comment:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        post_comment.assert_called_once()
        assert post_comment.call_args.args == ("42", "unknown", "done")

    def test_unknown_drift_returns_false(self, populated_db):
        drift = DriftRecord("YOK-42", "mystery", "a", "b")
        assert resync_mod._repair_drift(drift, [], populated_db) is False
