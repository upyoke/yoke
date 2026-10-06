"""Resync identity when public refs diverge from internal item ids.

An item's public ref renders as ``{public_item_prefix}-{project_sequence}``
and can diverge from the internal ``items.id``. These tests seed items
whose sequence differs from the internal id and prove the engine pairs,
compares, and repairs by internal id while displaying (and writing to
GitHub) the true public ref — stripping the ref's digits back into an id
would key the wrong item.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module). No live GitHub calls are made.
"""

# Imported pytest fixtures intentionally share names with test parameters.
# ruff: noqa: F811

from __future__ import annotations

from unittest import mock as mock

import yoke_core.engines.resync as resync_mod
from yoke_core.engines.resync import (
    DriftRecord as DriftRecord,
    PairedItem as PairedItem,
)

from runtime.api.fixtures.file_test_db import connect_test_db as connect_test_db
from runtime.api.engines._resync_test_helpers import (
    populated_db as populated_db,  # noqa: F401 — imported pytest fixture
    test_db,  # noqa: F401 — imported pytest fixture
)

# Internal id and public sequence intentionally differ.
DIVERGENT_ITEM_ID = 4600
DIVERGENT_SEQUENCE = 4544
DIVERGENT_REF = f"YOK-{DIVERGENT_SEQUENCE}"


def _insert_item(
    db_path: str,
    *,
    item_id: int,
    sequence: int,
    title: str,
    github_issue,
    status: str = "implementing",
    workflow: str = "issue",
) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, priority, workflow_id, workflow_version_id, "
            "source, spec, frozen, github_issue, project_id, project_sequence, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, 'medium', %s, "
            "(SELECT current_version_id FROM workflows WHERE id = %s), "
            "'manual', %s, 0, %s, 1, %s, '2026-01-01', '2026-01-01')",
            (
                item_id,
                title,
                status,
                workflow,
                workflow,
                f"{title} spec",
                github_issue,
                sequence,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TestStage1RefDivergence:
    def test_pairs_by_internal_id_and_renders_public_ref(
        self,
        populated_db,
        tmp_path,
    ):
        _insert_item(
            populated_db,
            item_id=DIVERGENT_ITEM_ID,
            sequence=DIVERGENT_SEQUENCE,
            title="Divergent item",
            github_issue="#310",
        )
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        gh_map = {
            "yoke": {
                310: {
                    "number": 310,
                    "title": f"[{DIVERGENT_REF}] Divergent item",
                    "labels": [],
                    "state": "OPEN",
                    "body": "",
                },
            },
        }
        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value=gh_map,
        ):
            paired, local_orphans, _, _ = resync_mod.stage1_linkage(
                populated_db,
                str(yoke_root),
            )

        by_ref = {item.ref: item for item in paired}
        assert DIVERGENT_REF in by_ref
        assert by_ref[DIVERGENT_REF].public_ref == DIVERGENT_REF
        # No label built from the internal id leaks out.
        assert f"YOK-{DIVERGENT_ITEM_ID}" not in by_ref
        assert all(orphan.ref != f"YOK-{DIVERGENT_ITEM_ID}" for orphan in local_orphans)

    def test_divergent_local_orphan_carries_internal_id(
        self,
        populated_db,
        tmp_path,
    ):
        _insert_item(
            populated_db,
            item_id=4700,
            sequence=4650,
            title="Divergent orphan",
            github_issue=None,
        )
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value={"yoke": {}},
        ):
            _, local_orphans, _, _ = resync_mod.stage1_linkage(
                populated_db,
                str(yoke_root),
            )

        orphan = next(o for o in local_orphans if o.ref == "YOK-4650")
        assert orphan.public_ref == "YOK-4650"

        # Orphan repair carries the canonical public ref into sync.
        with (
            mock.patch(
                "yoke_core.engines.resync_repair.resolve_project_github_auth",
            ),
            mock.patch(
                "yoke_core.engines.resync.backlog_github_sync.sync_item",
                return_value=0,
            ) as sync_item,
        ):
            ok, _, _ = resync_mod._repair_local_orphan_backlog(
                orphan.public_ref,
                orphan.project,
            )
        assert ok is True
        assert sync_item.call_args.args == ("YOK-4650",)


class TestStage2RefDivergence:
    def test_compare_keys_by_internal_id_not_ref_digits(self, populated_db):
        """A decoy item whose internal id equals the divergent item's
        public sequence must not absorb the comparison."""
        _insert_item(
            populated_db,
            item_id=DIVERGENT_ITEM_ID,
            sequence=DIVERGENT_SEQUENCE,
            title="Divergent item",
            github_issue="#310",
        )
        # Decoy: internal id == the divergent item's public sequence. Its
        # title matches GitHub, so keying by stripped ref digits would
        # report no drift.
        _insert_item(
            populated_db,
            item_id=DIVERGENT_SEQUENCE,
            sequence=9444,
            title="Wrong title",
            github_issue="#311",
        )
        gh_issues = {
            "yoke": {
                310: {
                    "number": 310,
                    "title": f"[{DIVERGENT_REF}] Wrong title",
                    "labels": [
                        {"name": "status:implementing"},
                        {"name": "priority:medium"},
                        {"name": "workflow:issue"},
                        {"name": "source:manual"},
                    ],
                    "state": "OPEN",
                    "body": "",
                },
            },
        }
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
        drifts = resync_mod.stage2_compare(paired, gh_issues, {}, populated_db)
        title_drifts = [d for d in drifts if d.field == "title"]
        assert len(title_drifts) == 1
        assert title_drifts[0].local == "Divergent item"
        assert title_drifts[0].github == "Wrong title"
        assert title_drifts[0].public_ref == DIVERGENT_REF
        assert title_drifts[0].ref == DIVERGENT_REF
