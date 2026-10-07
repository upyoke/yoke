"""Regression checks for resync public ref repairs."""

from __future__ import annotations

from runtime.api.engines.test_resync_ref_divergence import (
    DIVERGENT_ITEM_ID as DIVERGENT_ITEM_ID,
    DIVERGENT_REF as DIVERGENT_REF,
    DIVERGENT_SEQUENCE as DIVERGENT_SEQUENCE,
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
    _insert_item as _insert_item,
    connect_test_db as connect_test_db,
    mock as mock,
    populated_db as populated_db,
    resync_mod as resync_mod,
)


class TestRepairRefDivergence:
    def test_title_repair_writes_public_ref_not_internal_id(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        _insert_item(
            populated_db,
            item_id=DIVERGENT_ITEM_ID,
            sequence=DIVERGENT_SEQUENCE,
            title="Divergent item",
            github_issue="#310",
        )
        drift = DriftRecord(
            DIVERGENT_REF,
            "title",
            "Divergent item",
            "Wrong title",
            public_ref=DIVERGENT_REF,
        )
        paired = [
            PairedItem(
                DIVERGENT_REF,
                "/tmp/310.md",
                310,
                "backlog",
                "yoke",
                "",
                public_ref=DIVERGENT_REF,
            ),
        ]
        with (
            mock.patch(
                "yoke_core.engines.resync._is_dry_run",
                return_value=False,
            ),
            mock.patch(
                "yoke_core.engines.resync_repair.github_rest.update_issue",
                return_value=Issue(number=310, title="x", state="OPEN"),
            ) as update_issue,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs == {
            "project": "yoke",
            "number": 310,
            "title": f"[{DIVERGENT_REF}] Divergent item",
        }

    def test_epic_task_title_repair_renders_parent_public_ref(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        _insert_item(
            populated_db,
            item_id=1900,
            sequence=1890,
            title="Divergent epic",
            github_issue="#319",
            workflow="epic",
        )
        conn = connect_test_db(populated_db)
        try:
            conn.execute(
                "INSERT INTO epic_tasks (epic_id, task_num, title, status, "
                "body, github_issue) "
                "VALUES ('1900', 1, 'Task A', 'implementing', 'Body', '#320')",
            )
            conn.commit()
        finally:
            conn.close()

        drift = DriftRecord(
            "YOK-1890/task-001",
            "title",
            "Task A fixed",
            "Wrong",
            epic_public_ref="YOK-1890",
            task_num=1,
        )
        paired = [
            PairedItem(
                "YOK-1890/task-001",
                "epic_tasks:1900/1",
                320,
                "epic_task",
                "yoke",
                "",
                epic_public_ref="YOK-1890",
                task_num=1,
            ),
        ]
        with (
            mock.patch(
                "yoke_core.engines.resync._is_dry_run",
                return_value=False,
            ),
            mock.patch(
                "yoke_core.engines.resync_repair.github_rest.update_issue",
                return_value=Issue(number=320, title="x", state="OPEN"),
            ) as update_issue,
        ):
            assert resync_mod._repair_drift(drift, paired, populated_db) is True

        assert update_issue.call_args.kwargs["title"] == "[YOK-1890] 001 Task A fixed"
        assert update_issue.call_args.kwargs["number"] == 320

    def test_epic_task_issue_create_renders_parent_public_ref(self, populated_db):
        from yoke_core.domain.github_rest import Issue

        _insert_item(
            populated_db,
            item_id=1900,
            sequence=1890,
            title="Divergent epic",
            github_issue="#319",
            workflow="epic",
        )
        conn = connect_test_db(populated_db)
        try:
            conn.execute(
                "INSERT INTO epic_tasks (epic_id, task_num, title, status, "
                "body, github_issue) "
                "VALUES ('1900', 2, 'Task B', 'planned', 'Body', NULL)",
            )
            conn.commit()
        finally:
            conn.close()

        with (
            mock.patch(
                "yoke_core.engines.resync._is_dry_run",
                return_value=False,
            ),
            mock.patch(
                "yoke_core.engines.resync_repair_epic_task_issue."
                "github_rest.create_issue",
                return_value=Issue(number=321, title="t", state="OPEN"),
            ) as create_issue,
        ):
            # The github_issue write-back relays and is advisory, so the
            # repair outcome depends only on the create call above.
            ok = resync_mod._repair_local_orphan_epic_task(
                "YOK-1890",
                2,
                "yoke",
                populated_db,
            )

        assert ok is True
        assert create_issue.call_args.kwargs["title"] == "[YOK-1890] 002 Task B"
