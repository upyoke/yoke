"""Cutoff tests for lifecycle and deployment health checks.

Covers three HC sources that consume machine-config cutoff keys and run
against the shared meta-fixture schema in ``_doctor_meta_test_helpers``:
``hc_undeployed_done``, ``hc_premature_done``, ``hc_shepherd_lifecycle``.
Each test seeds one row below the cutoff and one at/above the cutoff,
runs the HC under a patched ``_resolve_repo_root`` pointing at
``tmp_path``, and asserts only the above-cutoff row appears in the
detail.

Sibling of test_doctor_meta.py (>=300 lines). Cutoff regressions live
here so the parent file does not grow. ``hc_cross_project_commits`` and
``hc_session_checkpoint_integrity`` cutoffs live in
``test_doctor_hc_meta_cutoffs_extra.py`` (they need bespoke schema/mock
scaffolding that would push this file past the 350-line hard cap).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant

from runtime.api.engines._doctor_meta_test_helpers import (
    _args,
    _insert_deployment_flow,
    _insert_item,
    _make_conn,
    _p,
    _results,
    _seed_project,
)
from yoke_core.engines._doctor_hc_cutoff_test_helpers import (
    _patch_repo_root,
    _write_cutoff,
)
from yoke_core.engines.doctor import (
    RecordCollector,
    hc_lifecycle_continuity,
    hc_premature_done,
    hc_shepherd_lifecycle,
    hc_undeployed_done,
)


def _seed_undeployed_done(conn, item_id: int) -> None:
    """Seed a done item that trips HC-undeployed-done."""
    days_old = 30
    updated = datetime.now(timezone.utc) - timedelta(days=days_old)
    _seed_project(conn, "yoke")
    _insert_item(
        conn,
        item_id,
        f"Stale undeployed item {item_id}",
        workflow_id="issue",
        status="done",
        deployed_to=None,
        updated_at=updated,
        created_at=updated,
    )
    _insert_deployment_flow(conn, f"flow-{item_id}")
    conn.commit()


class TestUndeployedDoneCutoff:
    def test_below_cutoff_excluded(self, tmp_path):
        conn = _make_conn()
        _seed_undeployed_done(conn, item_id=100)
        _seed_undeployed_done(conn, item_id=1700)
        _write_cutoff(tmp_path, "hc_undeployed_done_min_item_id", 1700)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_undeployed_done(conn, _args(), rec)

        result, detail = _results(rec)["HC-undeployed-done"]
        assert result == "WARN"
        assert "YOK-100" not in detail
        assert "YOK-1700" in detail

    def test_no_cutoff_keeps_legacy_behavior(self, tmp_path):
        conn = _make_conn()
        _seed_undeployed_done(conn, item_id=100)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_undeployed_done(conn, _args(), rec)

        result, detail = _results(rec)["HC-undeployed-done"]
        assert result == "WARN"
        assert "YOK-100" in detail


class TestPrematureDoneCutoff:
    def _seed(self, conn, item_id: int) -> None:
        _insert_item(
            conn,
            item_id,
            f"Done without merged_at {item_id}",
            status="done",
            merged_at=None,
        )

    def test_below_cutoff_excluded(self, tmp_path):
        conn = _make_conn()
        self._seed(conn, item_id=100)
        self._seed(conn, item_id=1473)
        _write_cutoff(tmp_path, "hc_premature_done_min_item_id", 1473)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_premature_done(conn, _args(), rec)

        result, detail = _results(rec)["HC-premature-done"]
        assert result == "WARN"
        assert "YOK-100" not in detail
        assert "YOK-1473" in detail

    def test_no_cutoff_keeps_legacy_behavior(self, tmp_path):
        conn = _make_conn()
        self._seed(conn, item_id=100)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_premature_done(conn, _args(), rec)

        result, detail = _results(rec)["HC-premature-done"]
        assert result == "WARN"
        assert "YOK-100" in detail


class TestShepherdLifecycleCutoff:
    def _seed_epic_without_verdict(self, conn, item_id: int) -> None:
        _insert_item(
            conn,
            item_id,
            f"Epic without verdict {item_id}",
            workflow_id="epic",
            status="planned",
        )

    def test_below_cutoff_excluded(self, tmp_path):
        conn = _make_conn()
        self._seed_epic_without_verdict(conn, item_id=100)
        self._seed_epic_without_verdict(conn, item_id=1700)
        _write_cutoff(tmp_path, "hc_shepherd_lifecycle_min_item_id", 1700)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_shepherd_lifecycle(conn, _args(), rec)

        result, detail = _results(rec)["HC-shepherd-lifecycle"]
        assert result == "WARN"
        assert "YOK-100" not in detail
        assert "YOK-1700" in detail

    def test_no_cutoff_keeps_legacy_behavior(self, tmp_path):
        conn = _make_conn()
        self._seed_epic_without_verdict(conn, item_id=100)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_shepherd_lifecycle(conn, _args(), rec)

        result, detail = _results(rec)["HC-shepherd-lifecycle"]
        assert result == "WARN"
        assert "YOK-100" in detail


class TestLifecycleContinuityCutoff:
    """Cutoff filters items whose current status was set before the cutoff.

    ``items.updated_at`` is the last-status-change timestamp; rows below
    the cutoff predate the writer fix and are grandfathered. The HC's
    matching predicate is unchanged — items above the cutoff whose
    current status lacks a matching item_status_transitions row still
    WARN.
    """

    _CUTOFF = "2026-05-16T17:55:00Z"
    _PRE_CUTOFF_TS = "2026-05-01T10:00:00Z"
    _POST_CUTOFF_TS = "2026-05-17T10:00:00Z"

    def _seed_item_without_event(
        self,
        conn,
        item_id: int,
        updated_at: str,
    ) -> None:
        """Insert an item with status='done' and no transition row."""
        _insert_item(
            conn,
            item_id,
            f"Done item without status-change event {item_id}",
            status="done",
            created_at=updated_at,
            updated_at=updated_at,
        )

    def test_below_cutoff_excluded(self, tmp_path):
        conn = _make_conn()
        self._seed_item_without_event(conn, 100, self._PRE_CUTOFF_TS)
        self._seed_item_without_event(conn, 1707, self._POST_CUTOFF_TS)
        _write_cutoff(
            tmp_path,
            "hc_lifecycle_continuity_min_status_change_at",
            self._CUTOFF,
        )

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_lifecycle_continuity(conn, _args(), rec)

        result, detail = _results(rec)["HC-lifecycle-continuity"]
        assert result == "WARN"
        assert "YOK-100" not in detail
        assert "YOK-1707" in detail

    def test_no_cutoff_keeps_legacy_behavior(self, tmp_path):
        conn = _make_conn()
        self._seed_item_without_event(conn, 100, self._PRE_CUTOFF_TS)

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_lifecycle_continuity(conn, _args(), rec)

        result, detail = _results(rec)["HC-lifecycle-continuity"]
        assert result == "WARN"
        assert "YOK-100" in detail

    def test_post_cutoff_with_matching_transition_passes(self, tmp_path):
        """Items above the cutoff that DO have a matching transition row
        do not WARN.

        Confirms the cutoff only suppresses grandfathered rows — it does
        not silence the HC's core matching predicate.
        """
        conn = _make_conn()
        self._seed_item_without_event(conn, 1708, self._POST_CUTOFF_TS)
        # Seed a matching item-level transition row for item 1708 → done.
        p = _p(conn)
        conn.execute(
            "INSERT INTO item_status_transitions "
            "(item_id, to_status, created_at) "
            f"VALUES (1708, 'done', {p})",
            (self._POST_CUTOFF_TS,),
        )
        conn.commit()
        _write_cutoff(
            tmp_path,
            "hc_lifecycle_continuity_min_status_change_at",
            self._CUTOFF,
        )

        rec = RecordCollector()
        with _patch_repo_root(tmp_path):
            hc_lifecycle_continuity(conn, _args(), rec)

        result, _ = _results(rec)["HC-lifecycle-continuity"]
        assert result == "PASS"


@pytest.mark.parametrize(
    "cutoff", [None, "2026-05-16T19:55:00.123456+02:00", "2026-05-16T17:55:00.123456Z"]
)
def test_lifecycle_cutoff_binds_native_instants(monkeypatch, cutoff):
    from yoke_core.engines import doctor_hc_meta_lifecycle as owner

    calls = []
    monkeypatch.setattr(owner._base, "_table_exists", lambda *_: True)
    monkeypatch.setattr(owner._base, "_read_str_cutoff", lambda *_: cutoff)
    monkeypatch.setattr(owner, "query_rows", lambda *args: calls.append(args) or [])
    owner.hc_lifecycle_continuity(object(), _args(), RecordCollector())
    params = calls[0][-1]
    assert params == (() if cutoff is None else (parse_instant(cutoff),))
    if params:
        assert isinstance(params[0], datetime) and params[0].microsecond == 123456


@pytest.mark.parametrize(
    "cutoff", ["2026-05-16", "2026-05-16 17:55:00+00", "2026-05-16T17:55:00"]
)
def test_invalid_lifecycle_cutoff_refuses_before_query(monkeypatch, cutoff):
    from yoke_core.engines import doctor_hc_meta_lifecycle as owner

    monkeypatch.setattr(owner._base, "_table_exists", lambda *_: True)
    monkeypatch.setattr(owner._base, "_read_str_cutoff", lambda *_: cutoff)
    monkeypatch.setattr(
        owner, "query_rows", lambda *_: pytest.fail("invalid cutoff reached SQL")
    )
    with pytest.raises(InvalidInstant):
        owner.hc_lifecycle_continuity(object(), _args(), RecordCollector())
