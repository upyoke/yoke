"""Lifetime-activity + streak widget tests — item_activity_days sourcing.

Companion to ``test_widgets.py``. Regression guard: the lifetime-activity
and streak widgets must source days from the append-only
``item_activity_days`` rollup, not from ``items.updated_at``. Re-touching
or deleting an item must not retroactively drop past days from the count.
"""

from __future__ import annotations

from datetime import date, timedelta

from yoke_core.board.db import BoardDB
from yoke_contracts.board.widgets import (
    _compute_achievement_streak,
    _compute_lifetime_activity,
    _compute_streak,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.board.tests.conftest import (
    insert_activity_day,
    insert_item_raw,
)


class TestLifetimeActivityRollupOnly:
    def _item_created_day(self, test_db_path: str, item_id: int, day: str) -> None:
        """Insert an item with ``created_at`` on *day* (no activity rows)."""
        insert_item_raw(test_db_path, [
            (item_id, f"item-{item_id}", "idea", "issue", "yoke", 0,
             f"{day}T12:00:00Z", f"{day}T12:00:00Z"),
        ])

    def _activity_day(self, test_db_path: str, item_id: int, day: str) -> None:
        """Record one activity-rollup day for *item_id*."""
        insert_activity_day(test_db_path, "yoke", item_id, day)

    def _delete_item(self, test_db_path: str, item_id: int) -> None:
        conn = connect_test_db(test_db_path)
        conn.execute("DELETE FROM items WHERE id = %s", (item_id,))
        conn.commit()
        conn.close()

    def test_lifetime_counts_day_from_rollup_not_items_updated_at(
        self, test_db_path
    ):
        """Day source of truth is item_activity_days, never items.updated_at."""
        # Item has updated_at=today but NO activity rows.
        self._item_created_day(test_db_path, 1, date.today().isoformat())
        with BoardDB(test_db_path) as db:
            active, _ = _compute_lifetime_activity(db, "yoke")
        assert active == 0

        # Record one activity day — now the day counts.
        self._activity_day(test_db_path, 1, date.today().isoformat())
        with BoardDB(test_db_path) as db:
            active, _ = _compute_lifetime_activity(db, "yoke")
        assert active == 1

    def test_deleting_item_does_not_shrink_lifetime_active_days(
        self, test_db_path
    ):
        """Regression: the 98% -> 96% drop happened because deleting an
        item also deleted its past ``updated_at``. With rollup-only
        sourcing the count must not decrease when items are removed."""
        today = date.today()
        day_a = (today - timedelta(days=2)).isoformat()
        day_b = (today - timedelta(days=1)).isoformat()
        day_c = today.isoformat()

        self._item_created_day(test_db_path, 1, day_a)
        self._item_created_day(test_db_path, 2, day_b)
        self._item_created_day(test_db_path, 3, day_c)
        self._activity_day(test_db_path, 1, day_a)
        self._activity_day(test_db_path, 2, day_b)
        self._activity_day(test_db_path, 3, day_c)

        with BoardDB(test_db_path) as db:
            before, _ = _compute_lifetime_activity(db, "yoke")
        assert before == 3

        # Delete the item whose day was the sole witness for day_a.
        self._delete_item(test_db_path, 1)

        with BoardDB(test_db_path) as db:
            after, _ = _compute_lifetime_activity(db, "yoke")
        assert after == 3, (
            "lifetime active days must not shrink when an item is deleted "
            "— item_activity_days is append-only"
        )

    def test_retouching_item_does_not_shrink_lifetime_active_days(
        self, test_db_path
    ):
        """Regression: `updated_at` moving forward must not silently unmark
        older days. The rollup captures every touch-day independently."""
        today = date.today()
        day_old = (today - timedelta(days=5)).isoformat()

        self._item_created_day(test_db_path, 1, day_old)
        self._activity_day(test_db_path, 1, day_old)

        with BoardDB(test_db_path) as db:
            before, _ = _compute_lifetime_activity(db, "yoke")
        assert before == 1

        # Simulate "re-touch": record a new activity day for the same item.
        # Crucially, the old day's row is NOT removed.
        self._activity_day(test_db_path, 1, today.isoformat())

        with BoardDB(test_db_path) as db:
            after, _ = _compute_lifetime_activity(db, "yoke")
        assert after == 2

    def test_same_day_retouch_counts_once(self, test_db_path):
        """Multiple touches on one day collapse to one rollup row — the
        unique (project, item, day) key is the dedup."""
        today = date.today().isoformat()
        self._item_created_day(test_db_path, 1, today)
        self._activity_day(test_db_path, 1, today)
        self._activity_day(test_db_path, 1, today)
        with BoardDB(test_db_path) as db:
            active, _ = _compute_lifetime_activity(db, "yoke")
        assert active == 1


class TestStreakRollupOnly:
    def test_streak_from_rollup_days(self, test_db_path):
        """Streak counts consecutive days with activity rows,
        independent of items.updated_at."""
        today = date.today()
        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0,
             f"{today.isoformat()}T12:00:00Z",
             f"{today.isoformat()}T12:00:00Z"),
        ])
        # Three consecutive days with activity.
        for offset in range(3):
            day = (today - timedelta(days=offset)).isoformat()
            insert_activity_day(test_db_path, "yoke", 1, day)
        with BoardDB(test_db_path) as db:
            streak = _compute_streak(db, "yoke", 365)
        assert streak == 3

    def test_streak_ignores_items_updated_at(self, test_db_path):
        """If only items.updated_at shows today but there's no activity
        row, the streak must be zero."""
        today = date.today().isoformat()
        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0,
             f"{today}T12:00:00Z", f"{today}T12:00:00Z"),
        ])
        with BoardDB(test_db_path) as db:
            streak = _compute_streak(db, "yoke", 365)
        assert streak == 0


class TestCommitFallback:
    """Days with commits but no rollup rows still keep the streak alive."""

    def _init_repo_with_commits_on_days(
        self, repo_dir, days: "list[str]"
    ) -> None:
        import os
        import subprocess
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.email", "t@t"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "config", "user.name", "t"],
            check=True,
        )
        for i, day in enumerate(days):
            f = repo_dir / f"f{i}.txt"
            f.write_text(f"v{i}\n")
            subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True)
            ts = f"{day}T12:00:00"
            env = {
                "GIT_AUTHOR_DATE": ts,
                "GIT_COMMITTER_DATE": ts,
                "PATH": os.environ.get("PATH", ""),
            }
            subprocess.run(
                ["git", "-C", str(repo_dir), "commit", "-q", "-m", f"c{i}"],
                check=True, env=env,
            )

    def _wire_checkout(self, test_db_path: str, repo_dir) -> None:
        register_machine_checkout(
            repo_dir.parent / "machine-config",
            repo_dir,
            1,
        )

    def test_streak_unbroken_by_commit_only_day(self, test_db_path, tmp_path):
        """Two activity-days bracketing a commit-only day still streak as 3."""
        today = date.today()
        d_act_old = (today - timedelta(days=2)).isoformat()
        d_commit_only = (today - timedelta(days=1)).isoformat()
        d_act_today = today.isoformat()

        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0,
             f"{d_act_old}T12:00:00Z", f"{d_act_today}T12:00:00Z"),
        ])
        for d in (d_act_old, d_act_today):
            insert_activity_day(test_db_path, "yoke", 1, d)

        repo_dir = tmp_path / "repo"
        self._init_repo_with_commits_on_days(repo_dir, [d_commit_only])
        self._wire_checkout(test_db_path, repo_dir)

        with BoardDB(test_db_path) as db:
            streak = _compute_streak(db, "yoke", 365)
        assert streak == 3

    def test_achievement_streak_unbroken_by_commit_only_day(
        self, test_db_path, tmp_path,
    ):
        """Commit-only days must extend the achievement-streak run too,
        so the badge agrees with the sparkline on what counts as active.

        Three consecutive days, middle day commit-only — the achievement
        streak (longest run in window) should be 3, not 1.
        """
        today = date.today()
        d_act_old = (today - timedelta(days=2)).isoformat()
        d_commit_only = (today - timedelta(days=1)).isoformat()
        d_act_today = today.isoformat()

        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0,
             f"{d_act_old}T12:00:00Z", f"{d_act_today}T12:00:00Z"),
        ])
        for d in (d_act_old, d_act_today):
            insert_activity_day(test_db_path, "yoke", 1, d)

        repo_dir = tmp_path / "repo"
        self._init_repo_with_commits_on_days(repo_dir, [d_commit_only])
        self._wire_checkout(test_db_path, repo_dir)

        with BoardDB(test_db_path) as db:
            best = _compute_achievement_streak(db, "yoke")
        assert best == 3, (
            "achievement streak must union commit-days so a commit-only "
            "day between two activity-days does not break the run"
        )

    def test_lifetime_counts_commit_only_day(self, test_db_path, tmp_path):
        """A commit-only day counts toward lifetime active_days."""
        today = date.today()
        d_act = (today - timedelta(days=1)).isoformat()
        d_commit_only = today.isoformat()

        insert_item_raw(test_db_path, [
            (1, "item-1", "idea", "issue", "yoke", 0,
             f"{d_act}T12:00:00Z", f"{d_act}T12:00:00Z"),
        ])
        insert_activity_day(test_db_path, "yoke", 1, d_act)

        repo_dir = tmp_path / "repo"
        self._init_repo_with_commits_on_days(repo_dir, [d_commit_only])
        self._wire_checkout(test_db_path, repo_dir)

        with BoardDB(test_db_path) as db:
            active, _ = _compute_lifetime_activity(db, "yoke")
        assert active == 2
