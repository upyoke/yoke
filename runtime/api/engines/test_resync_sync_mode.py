"""Resync engine behavior for backlog-only projects.

``projects.github_sync_mode='backlog_only'`` removes a project from the
sync universe: no GitHub fetch, no orphan classification, no repair —
and the engine names the exclusion in mode language instead of surfacing
an auth error. The skip is not a failure: exit codes reflect the enabled
projects only.

Pytest fixtures (test_db, populated_db) are shared via
_resync_test_helpers (private module). No live GitHub calls are made.
"""

from __future__ import annotations

from unittest import mock

import yoke_core.engines.resync as resync_mod
from yoke_core.domain.projects_github_sync_mode import GITHUB_SYNC_BACKLOG_ONLY
from yoke_core.engines.resync_detect_fetch import (
    SYNC_DISABLED_KEY,
    _fetch_gh_issues_per_project,
    _project_sync_disabled,
)

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.engines._resync_test_helpers import (  # noqa: F401 — fixtures
    populated_db,
    test_db,
)

# populated_db seeds items 42 (linked to GH #100) and 43 (linked to #101).
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"
TEST_DONE_ITEM_REF = f"YOK-{TEST_ITEM_ID + 1}"


def _set_sync_mode(db_path: str, slug: str, mode: str) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "UPDATE projects SET github_sync_mode = %s WHERE slug = %s",
            (mode, slug),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_unlinked_item(db_path: str, item_id: int) -> None:
    """Seed an item with NO github_issue — the mass-create hazard row."""
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO items
            (id, title, status, priority, type, source, spec, frozen,
             github_issue, project_id, project_sequence, created_at, updated_at)
            VALUES (%s, 'DB-only item', 'idea', 'medium', 'issue', 'manual',
                    'Body', 0, NULL, 1, %s, '2026-01-01', '2026-01-01')
            """,
            (item_id, item_id),
        )
        conn.commit()
    finally:
        conn.close()


class TestFetchSkipsExcludedYoke:
    def test_yoke_absent_from_map_is_not_fetched(self):
        """No yoke auth resolution when the caller excluded yoke."""

        def _explode(project, *args, **kwargs):
            raise AssertionError(
                f"resolver called for excluded project {project!r}"
            )

        with mock.patch(
            "yoke_core.engines.resync_detect_fetch.resolve_project_github_auth",
            side_effect=_explode,
        ):
            result = _fetch_gh_issues_per_project({})

        assert result == {}

    def test_sentinel_predicate_matches_only_sentinel(self):
        assert _project_sync_disabled({SYNC_DISABLED_KEY: "backlog_only"})
        assert not _project_sync_disabled({})
        assert not _project_sync_disabled({100: {"number": 100}})
        assert not _project_sync_disabled({"_auth_error": "missing_token"})


class TestStage1LinkageBacklogOnly:
    def test_backlog_only_project_items_never_become_orphans(
        self, populated_db, tmp_path,
    ):
        """The disaster case: unlinked items in a backlog-only project
        must NOT classify as local orphans (a --fix run would create
        them as GitHub issues)."""
        _set_sync_mode(populated_db, "yoke", GITHUB_SYNC_BACKLOG_ONLY)
        _insert_unlinked_item(populated_db, 4777)
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)

        observed_maps: list[dict] = []

        def fake_fetch(project_map):
            observed_maps.append(dict(project_map))
            return {}

        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            side_effect=fake_fetch,
        ):
            paired, local_orphans, gh_orphans, gh_by_project = (
                resync_mod.stage1_linkage(populated_db, str(yoke_root))
            )

        # yoke was excluded from the fetch map entirely.
        assert observed_maps and "yoke" not in observed_maps[0]
        # Its items (including the unlinked one) are not classified at all.
        assert paired == []
        assert local_orphans == []
        assert gh_orphans == []
        # The per-project value carries the sync-disabled sentinel.
        assert gh_by_project["yoke"] == {
            SYNC_DISABLED_KEY: GITHUB_SYNC_BACKLOG_ONLY,
        }

    def test_enabled_projects_still_classify(self, populated_db, tmp_path):
        """Sync mode defaults to enabled — behavior unchanged."""
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)
        gh_map = {
            "yoke": {
                100: {"number": 100, "title": f"[{TEST_ITEM_REF}] Test item",
                      "labels": [], "state": "OPEN", "body": ""},
            }
        }

        with mock.patch(
            "yoke_core.engines.resync._fetch_gh_issues_per_project",
            return_value=gh_map,
        ):
            paired, local_orphans, _, _ = resync_mod.stage1_linkage(
                populated_db, str(yoke_root),
            )

        assert {item.id for item in paired} == {TEST_ITEM_REF}
        assert any(oid == TEST_DONE_ITEM_REF for oid, *_ in local_orphans)


class TestEngineMainBacklogOnly:
    def test_detect_names_the_mode_and_exits_zero(
        self, populated_db, tmp_path, capsys,
    ):
        """`yoke resync` on a backlog-only universe: clear mode-language
        message, zero drift, exit 0 — never an auth error."""
        _set_sync_mode(populated_db, "yoke", GITHUB_SYNC_BACKLOG_ONLY)
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)

        def _explode(project, *args, **kwargs):
            raise AssertionError(
                f"resolver called for excluded project {project!r}"
            )

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch."
                "resolve_project_github_auth",
                side_effect=_explode,
            ),
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=str(yoke_root),
            ),
        ):
            rc = resync_mod.main(["--detect-only"])

        out = capsys.readouterr().out
        assert rc == 0, out
        assert "GitHub Sync Disabled (per-project)" in out
        assert (
            "project 'yoke' github_sync_mode=backlog_only" in out
        )
        assert "Local orphans: 0" in out
        assert "Auth Failures" not in out

    def test_fix_repairs_nothing_for_backlog_only_project(
        self, populated_db, tmp_path, capsys,
    ):
        """--fix must not create GitHub issues for a backlog-only project."""
        _set_sync_mode(populated_db, "yoke", GITHUB_SYNC_BACKLOG_ONLY)
        _insert_unlinked_item(populated_db, 4778)
        yoke_root = tmp_path / "state"
        (yoke_root / "backlog").mkdir(parents=True)

        def _no_repair(*args, **kwargs):
            raise AssertionError(
                "repair invoked for a backlog-only project's item"
            )

        with (
            mock.patch(
                "yoke_core.engines.resync_detect_fetch."
                "resolve_project_github_auth",
                side_effect=AssertionError("resolver called"),
            ),
            mock.patch(
                "yoke_core.engines.resync._repair_local_orphan_backlog",
                side_effect=_no_repair,
            ),
            mock.patch(
                "yoke_core.engines.resync._resolve_yoke_root",
                return_value=str(yoke_root),
            ),
        ):
            rc = resync_mod.main(["--fix"])

        out = capsys.readouterr().out
        assert rc == 0, out
        assert "0 repaired, 0 failed" in out
