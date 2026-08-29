# ruff: noqa: F811
"""Mutation tests — execute_close.

Cover reason validation, delivery-tail/merge guards, terminal lane cleanup, idempotent
re-close, resolution-ref normalization, and the dry-run skip path that
suppresses GitHub side effects but still rebuilds the board.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.fixtures.backlog_inserts import insert_item_worktree
from yoke_core.domain import backlog


def _seed_active_item_lane(path, *, item_id: int, branch: str) -> None:
    conn = _conn(path)
    try:
        insert_item_worktree(
            conn,
            item_id=item_id,
            branch=branch,
            lane_role="implementation",
        )
    finally:
        conn.close()


def _item_lane_state(path, *, item_id: int, branch: str) -> str:
    conn = _conn(path)
    try:
        row = conn.execute(
            "SELECT state FROM item_worktrees WHERE item_id=%s AND branch=%s",
            (item_id, branch),
        ).fetchone()
        return str(row[0])
    finally:
        conn.close()


class TestExecuteClose:
    def test_basic_close_sets_resolution(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea", frozen=1)
        out = io.StringIO()

        with (
            _patch_externals() as patched,
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
        ):
            result = backlog.execute_close(
                item_id=10,
                reason="duplicate",
                resolution_ref="YOK-33",
                resolution_comment="Superseded by YOK-33",
                out=out,
            )

        assert result["success"] is True
        assert _item_field(tmp_db, 10, "status") == "cancelled"
        assert _item_field(tmp_db, 10, "resolution") == "duplicate"
        assert _item_field(tmp_db, 10, "resolution_ref") == "YOK-33"
        assert _item_field(tmp_db, 10, "resolution_comment") == "Superseded by YOK-33"
        assert _item_field(tmp_db, 10, "frozen") == 0
        patched["_post_comment"].return_value = True
        patched["_close_issue"].return_value = True
        patched["_post_comment"].assert_called_once_with(10, "idea", "cancelled", out)
        patched["_close_issue"].assert_called_once_with(10, out)
        patched["_rebuild_board"].assert_called_once_with(out)

    def test_basic_close_preserves_context_free_numeric_resolution_ref(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(
                item_id=10,
                reason="duplicate",
                resolution_ref="33",
                out=out,
            )

        assert result["success"] is True
        assert _item_field(tmp_db, 10, "resolution_ref") == "33"

    def test_close_idempotent_same_reason(self, tmp_db):
        _seed_item(tmp_db, id=10, status="cancelled", resolution="obsolete")
        out = io.StringIO()

        with (
            _patch_externals() as patched,
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
        ):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result["success"] is True
        assert result.get("noop") is True
        assert "no-op" in out.getvalue()
        patched["_post_comment"].assert_not_called()
        patched["_close_issue"].assert_not_called()

    def test_close_rejects_empty_reason(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "  ", out=out)

        assert result["success"] is False
        assert "non-empty" in result["error"]

    def test_close_accepts_a_free_text_reason(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "superseded by later work", out=out)

        assert result["success"] is True
        assert _item_field(tmp_db, 10, "resolution") == "superseded by later work"

    def test_close_rejects_delivery_tail(self, tmp_db):
        _seed_item(tmp_db, id=10, status="implemented")
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "wontfix", out=out)

        assert result["success"] is False
        assert "delivery tail" in result["error"]

    def test_close_rejects_merge_evidence(self, tmp_db):
        _seed_item(tmp_db, id=10, merged_at="2026-01-01T00:00:00Z")
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result["success"] is False
        assert "merge evidence" in result["error"]

    def test_close_rejects_active_worktree(self, tmp_db):
        _seed_item(tmp_db, id=10)
        _seed_active_item_lane(tmp_db, item_id=10, branch="YOK-10")
        out = io.StringIO()

        with _patch_externals(), mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result["success"] is False
        assert "active worktree lanes (YOK-10)" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "idea"
        assert (
            _item_lane_state(
                tmp_db,
                item_id=10,
                branch="YOK-10",
            )
            == "active"
        )

    def test_close_emits_item_status_changed_event(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        out = io.StringIO()

        with (
            _patch_externals() as patched,
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
        ):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result["success"] is True
        emit_calls = [
            call
            for call in patched["_emit_event"].call_args_list
            if call.args[0] == "ItemStatusChanged"
        ]
        assert len(emit_calls) == 1, (
            f"expected exactly one ItemStatusChanged emit, got "
            f"{patched['_emit_event'].call_args_list}"
        )
        args = emit_calls[0].args
        assert args[1] == 10
        assert args[2]["from_status"] == "idea"
        assert args[2]["to_status"] == "cancelled"
        assert args[2]["source"] == "execute-close"

    def test_close_fires_cancel_claims_hook(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        out = io.StringIO()

        with (
            _patch_externals(),
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
            mock.patch(
                "yoke_core.domain.path_claims_item_hook.cancel_claims_on_item_terminal",
                return_value=2,
            ) as cancel_mock,
        ):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result["success"] is True
        cancel_mock.assert_called_once()
        _, kwargs = cancel_mock.call_args
        assert kwargs["item_id"] == 10
        assert kwargs["new_status"] == "cancelled"
        assert kwargs["commit"] is False
        assert "Cancelled 2 non-terminal path claim(s) for YOK-10" in out.getvalue()

    def test_close_noop_skips_event_and_hook(self, tmp_db):
        _seed_item(tmp_db, id=10, status="cancelled", resolution="obsolete")
        out = io.StringIO()

        with (
            _patch_externals() as patched,
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
            mock.patch(
                "yoke_core.domain.path_claims_item_hook.cancel_claims_on_item_terminal",
            ) as cancel_mock,
        ):
            result = backlog.execute_close(10, "obsolete", out=out)

        assert result.get("noop") is True
        emit_calls = [
            call
            for call in patched["_emit_event"].call_args_list
            if call.args[0] == "ItemStatusChanged"
        ]
        assert emit_calls == []
        cancel_mock.assert_not_called()

    def test_close_skips_github_in_dry_run(self, tmp_db):
        _seed_item(tmp_db, id=10)
        out = io.StringIO()

        with (
            _patch_externals() as patched,
            mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}),
            mock.patch(
                "yoke_core.domain.backlog_updates._is_dry_run", return_value=True
            ),
        ):
            result = backlog.execute_close(10, "wontfix", out=out)

        assert result["success"] is True
        assert "[DRY-RUN] Skipping GitHub: close + comment for YOK-10" in out.getvalue()
        patched["_post_comment"].assert_not_called()
        patched["_close_issue"].assert_not_called()
        patched["_rebuild_board"].assert_called_once_with(out)
