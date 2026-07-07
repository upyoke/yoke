"""Close-path dependency reconciliation tests for ``yoke_core.domain.backlog``.

Shared fixtures and seed helpers are imported from ``test_backlog``.
Sibling files in the ``test_backlog_queries_*`` family own structured-write,
freeze-immutability, and the smaller query helpers.
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from yoke_core.domain import backlog
from yoke_core.domain import backlog_updates
from runtime.api.test_backlog import (
    _conn,
    _item_field,
    _p,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)


def _seed_dependency(path, dependent, blocking, gate_point="activation", satisfaction="status:done"):
    """Insert an item_dependencies row for close-path reconciliation tests."""
    conn = _conn(path)
    p = _p(conn)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, "
        "source, rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, 'test', 'seeded by test', '{{}}', '2026-01-01T00:00:00Z')",
        (dependent, blocking, gate_point, satisfaction),
    )
    conn.commit()
    conn.close()


def _dependency_rows(path, *, dependent=None, blocking=None):
    """Return rows matching the given direction filter."""
    conn = _conn(path)
    p = _p(conn)
    select = "SELECT dependent_item, blocking_item, gate_point, satisfaction FROM item_dependencies "
    if dependent is not None and blocking is not None:
        rows = conn.execute(
            select + f"WHERE dependent_item = {p} AND blocking_item = {p} ORDER BY gate_point",
            (dependent, blocking),
        ).fetchall()
    elif dependent is not None:
        rows = conn.execute(
            select + f"WHERE dependent_item = {p} ORDER BY blocking_item, gate_point",
            (dependent,),
        ).fetchall()
    elif blocking is not None:
        rows = conn.execute(
            select + f"WHERE blocking_item = {p} ORDER BY dependent_item, gate_point",
            (blocking,),
        ).fetchall()
    else:
        rows = conn.execute(select + "ORDER BY id").fetchall()
    conn.close()
    return [tuple(r) for r in rows]


class TestExecuteCloseDependencyReconciliation:
    """close path must reconcile item_dependencies."""

    def test_close_removes_outbound_rows(self, tmp_db):
        """AC-1: outbound rows (cancelled item as dependent) are always removed."""
        _seed_item(tmp_db, id=1270, status="refined-idea")
        _seed_item(tmp_db, id=1269, status="refined-idea")
        _seed_dependency(
            tmp_db,
            dependent="YOK-1270",
            blocking="YOK-1269",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(1270, "wontfix", out=out)

        assert result["success"] is True
        assert _dependency_rows(tmp_db, dependent="YOK-1270") == []
        assert result["dependency_reconciliation"]["outbound_removed"] == [
            {
                "blocking_item": "YOK-1269",
                "gate_point": "integration",
                "satisfaction": "fact:merged",
            }
        ]

    def test_close_removes_absorbed_inbound_rows(self, tmp_db):
        """AC-2: inbound rows where resolution_ref matches dependent are removed."""
        _seed_item(tmp_db, id=1218, status="refined-idea")
        _seed_item(tmp_db, id=1185, status="implementing")
        _seed_dependency(
            tmp_db,
            dependent="YOK-1185",
            blocking="YOK-1218",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(
                1218, "duplicate", resolution_ref="YOK-1185", out=out
            )

        assert result["success"] is True
        assert _dependency_rows(tmp_db, blocking="YOK-1218") == []
        recon = result["dependency_reconciliation"]
        assert recon["absorbed_inbound_removed"] == [
            {
                "dependent_item": "YOK-1185",
                "gate_point": "integration",
                "satisfaction": "fact:merged",
            }
        ]
        assert recon["preserved_ambiguous"] == []

    def test_close_removes_absorbed_inbound_rows_with_numeric_resolution_ref(self, tmp_db):
        """Numeric refs should normalize to YOK-N before absorbed-row matching."""
        _seed_item(tmp_db, id=1218, status="refined-idea")
        _seed_item(tmp_db, id=1185, status="implementing")
        _seed_dependency(
            tmp_db,
            dependent="YOK-1185",
            blocking="YOK-1218",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(
                1218, "duplicate", resolution_ref="1185", out=out
            )

        assert result["success"] is True
        assert _item_field(tmp_db, 1218, "resolution_ref") == "YOK-1185"
        assert _dependency_rows(tmp_db, blocking="YOK-1218") == []
        recon = result["dependency_reconciliation"]
        assert recon["absorbed_inbound_removed"] == [
            {
                "dependent_item": "YOK-1185",
                "gate_point": "integration",
                "satisfaction": "fact:merged",
            }
        ]
        assert recon["preserved_ambiguous"] == []

    def test_close_preserves_ambiguous_inbound_rows_and_warns(self, tmp_db):
        """AC-3: inbound rows with no deterministic rule are preserved + warned."""
        _seed_item(tmp_db, id=1269, status="refined-idea")
        _seed_item(tmp_db, id=1270, status="refined-idea")
        _seed_dependency(
            tmp_db,
            dependent="YOK-1270",
            blocking="YOK-1269",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(1269, "obsolete", out=out)

        assert result["success"] is True
        preserved = _dependency_rows(tmp_db, blocking="YOK-1269")
        assert preserved == [
            ("YOK-1270", "YOK-1269", "integration", "fact:merged")
        ]

        out_text = out.getvalue()
        assert "Warning" in out_text
        assert "YOK-1270 <- YOK-1269" in out_text
        assert "gate=integration" in out_text
        assert "satisfaction=fact:merged" in out_text
        assert "resolution=obsolete" in out_text

        recon = result["dependency_reconciliation"]
        assert recon["preserved_ambiguous"] == [
            {
                "dependent_item": "YOK-1270",
                "blocking_item": "YOK-1269",
                "gate_point": "integration",
                "satisfaction": "fact:merged",
            }
        ]
        assert recon["absorbed_inbound_removed"] == []

    def test_close_with_no_dependency_rows_is_clean(self, tmp_db):
        """AC-4: close with zero dep rows emits no warning and no reconciliation."""
        _seed_item(tmp_db, id=10, status="idea")

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "wontfix", out=out)

        assert result["success"] is True
        assert "Warning" not in out.getvalue()
        assert "Reconciled" not in out.getvalue()
        recon = result["dependency_reconciliation"]
        assert recon["outbound_removed"] == []
        assert recon["absorbed_inbound_removed"] == []
        assert recon["preserved_ambiguous"] == []

    def test_close_mixed_outbound_and_inbound(self, tmp_db):
        """Cancelling an item both unblocks itself and cleans absorbed inbound."""
        _seed_item(tmp_db, id=50, status="refined-idea")
        _seed_item(tmp_db, id=60, status="refined-idea")  # outbound blocker
        _seed_item(tmp_db, id=70, status="implementing")  # absorbed-self parent
        _seed_dependency(
            tmp_db,
            dependent="YOK-50",
            blocking="YOK-60",
            gate_point="activation",
            satisfaction="status:done",
        )
        _seed_dependency(
            tmp_db,
            dependent="YOK-70",
            blocking="YOK-50",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(
                50, "duplicate", resolution_ref="YOK-70", out=out
            )

        assert result["success"] is True
        assert _dependency_rows(tmp_db, dependent="YOK-50") == []
        assert _dependency_rows(tmp_db, blocking="YOK-50") == []

        recon = result["dependency_reconciliation"]
        assert len(recon["outbound_removed"]) == 1
        assert recon["outbound_removed"][0]["blocking_item"] == "YOK-60"
        assert len(recon["absorbed_inbound_removed"]) == 1
        assert recon["absorbed_inbound_removed"][0]["dependent_item"] == "YOK-70"
        assert recon["preserved_ambiguous"] == []

    def test_close_reconciliation_and_status_commit_atomically(self, tmp_db):
        """AC-5: reconciliation and status change commit in one transaction.

        Simulate a reconciliation failure by making ``_update_item_multi``
        raise after the DELETE has run on the same connection. The
        expected outcome is that neither the item status change nor the
        dependency deletion are persisted: a crash between DELETE and
        UPDATE must not leave behind a half-applied cancel.
        """
        _seed_item(tmp_db, id=1270, status="refined-idea")
        _seed_item(tmp_db, id=1269, status="refined-idea")
        _seed_dependency(
            tmp_db,
            dependent="YOK-1270",
            blocking="YOK-1269",
            gate_point="integration",
            satisfaction="fact:merged",
        )

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}), \
             mock.patch.object(
                 backlog_updates,
                 "_update_item_multi",
                 side_effect=RuntimeError("boom"),
             ):
            with pytest.raises(RuntimeError, match="boom"):
                backlog.execute_close(1270, "wontfix", out=out)

        # Status must not have flipped to cancelled.
        assert _item_field(tmp_db, 1270, "status") == "refined-idea"
        # Outbound row must still be present (rollback on connection close).
        rows = _dependency_rows(tmp_db, dependent="YOK-1270")
        assert rows == [
            ("YOK-1270", "YOK-1269", "integration", "fact:merged")
        ]

    def test_existing_guards_still_block_reconciliation(self, tmp_db):
        """AC-6: delivery-tail, merge-evidence, worktree guards still stop
        the close before reconciliation touches item_dependencies."""
        # delivery-tail
        _seed_item(tmp_db, id=1, status="implemented")
        _seed_dependency(
            tmp_db, dependent="YOK-99", blocking="YOK-1",
            gate_point="integration", satisfaction="fact:merged",
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(1, "wontfix", out=out)
        assert result["success"] is False
        # Row is untouched.
        assert _dependency_rows(tmp_db, blocking="YOK-1") == [
            ("YOK-99", "YOK-1", "integration", "fact:merged")
        ]

        # merge-evidence
        _seed_item(tmp_db, id=2, merged_at="2026-01-01T00:00:00Z")
        _seed_dependency(
            tmp_db, dependent="YOK-2", blocking="YOK-77",
            gate_point="activation", satisfaction="status:done",
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(2, "obsolete", out=out)
        assert result["success"] is False
        assert _dependency_rows(tmp_db, dependent="YOK-2") == [
            ("YOK-2", "YOK-77", "activation", "status:done")
        ]

        # active worktree
        _seed_item(tmp_db, id=3, worktree="YOK-3")
        _seed_dependency(
            tmp_db, dependent="YOK-3", blocking="YOK-88",
            gate_point="activation", satisfaction="status:done",
        )
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(3, "obsolete", out=out)
        assert result["success"] is False
        assert _dependency_rows(tmp_db, dependent="YOK-3") == [
            ("YOK-3", "YOK-88", "activation", "status:done")
        ]
