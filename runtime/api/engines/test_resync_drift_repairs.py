"""Regression checks for resync drift repairs."""

from __future__ import annotations

from runtime.api.engines.test_resync_repair import (
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
    _auth_resolver as _auth_resolver,
    mock as mock,
    populated_db as populated_db,
    resync_mod as resync_mod,
)


class TestRepairDrift:
    def test_title_drift_backlog_edits_issue(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord(
            "YOK-42", "title", "Correct title", "Wrong title", public_ref="YOK-42"
        )
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair.github_rest.update_issue",
                return_value=Issue(
                    number=100, title="[YOK-42] Correct title", state="OPEN"
                ),
            ) as update_issue,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs == {
            "project": "yoke",
            "number": 100,
            "title": "[YOK-42] Correct title",
        }

    def test_title_drift_epic_task_uses_parent_prefix(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord(
            "YOK-1246/task-001",
            "title",
            "Task one fixed",
            "Wrong",
            epic_public_ref="YOK-1246",
            task_num=1,
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair.github_rest.update_issue",
                return_value=Issue(number=200, title="x", state="OPEN"),
            ) as update_issue,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs["title"] == "[YOK-1246] 001 Task one fixed"
        assert update_issue.call_args.kwargs["number"] == 200

    def test_body_drift_backlog_uses_domain_sync(self, populated_db):
        drift = DriftRecord(
            "YOK-42", "body", "<local>", "<github>", public_ref="YOK-42"
        )
        paired = [
            PairedItem(
                "YOK-42",
                "/tmp/042.md",
                100,
                "backlog",
                "externalwebapp",
                "",
                public_ref="YOK-42",
            )
        ]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_body",
            return_value=0,
        ) as sync_body:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync_body.assert_called_once()
        assert sync_body.call_args.args == ("42",)

    def test_body_drift_epic_task_uses_python_sync(self, populated_db):
        drift = DriftRecord(
            "YOK-1246/task-001",
            "body",
            "<local>",
            "<github>",
            epic_public_ref="YOK-1246",
            task_num=1,
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        with mock.patch(
            "yoke_core.engines.resync.epic_task_sync.sync_task_body", return_value=0
        ) as sync:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync.assert_called_once()
        assert sync.call_args.args == ("1246", 1)

    def test_label_drift_backlog_uses_domain_sync(self, populated_db):
        drift = DriftRecord(
            "YOK-42",
            "label-status",
            "status:done",
            "status:implementing",
            public_ref="YOK-42",
        )
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
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
        drift = DriftRecord(
            "YOK-42", "label-owner", "owner:ben", "owner:yoke-core", public_ref="YOK-42"
        )
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.sync_labels",
            return_value=0,
        ) as sync_labels:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        sync_labels.assert_called_once()
        assert sync_labels.call_args.args == ("42",)

    def test_label_frozen_dry_run_returns_true(self, populated_db):
        drift = DriftRecord(
            "YOK-42",
            "label-frozen",
            "frozen:true",
            "frozen:absent",
            public_ref="YOK-42",
        )
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
        with mock.patch("yoke_core.engines.resync._is_dry_run", return_value=True):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

    def test_state_drift_backlog_uses_domain_close(self, populated_db):
        drift = DriftRecord("YOK-42", "state", "CLOSED", "OPEN", public_ref="YOK-42")
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
        with mock.patch(
            "yoke_core.engines.resync.backlog_github_sync.close_issue",
            return_value=0,
        ) as close_issue:
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        close_issue.assert_called_once()
        assert close_issue.call_args.args == ("42",)

    def test_state_drift_epic_task_uses_issue_close(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        drift = DriftRecord(
            "YOK-1246/task-001",
            "state",
            "CLOSED",
            "OPEN",
            epic_public_ref="YOK-1246",
            task_num=1,
        )
        paired = [
            PairedItem(
                "YOK-1246/task-001",
                "epic_tasks:1246/1",
                200,
                "epic_task",
                "externalwebapp",
                "org/externalwebapp",
                epic_public_ref="YOK-1246",
                task_num=1,
            )
        ]
        with (
            mock.patch("yoke_core.engines.resync._is_dry_run", return_value=False),
            mock.patch(
                "yoke_core.engines.resync_repair.github_rest.set_issue_state",
                return_value=Issue(number=200, title="x", state="CLOSED"),
            ) as set_state,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        assert set_state.call_args.kwargs == {
            "project": "externalwebapp",
            "number": 200,
            "state": "closed",
        }

    def test_comment_drift_backlog_posts_via_domain_sync(self, populated_db):
        drift = DriftRecord(
            "YOK-42", "comment", "has-status-comment", "missing", public_ref="YOK-42"
        )
        paired = [
            PairedItem(
                "YOK-42", "/tmp/042.md", 100, "backlog", "yoke", "", public_ref="YOK-42"
            )
        ]
        with (
            mock.patch(
                "yoke_core.engines.resync._query_item_status", return_value="done"
            ),
            mock.patch(
                "yoke_core.engines.resync.backlog_github_sync.post_comment",
                return_value=0,
            ) as post_comment,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True
        post_comment.assert_called_once()
        assert post_comment.call_args.args == ("42", "unknown", "done")

    def test_unknown_drift_returns_false(self, populated_db):
        drift = DriftRecord("YOK-42", "mystery", "a", "b", public_ref="YOK-42")
        assert resync_mod._repair_drift(drift, [], populated_db) is False
