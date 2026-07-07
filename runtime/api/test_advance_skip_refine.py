"""Pytest suite for ``yoke_core.domain.advance_skip`` — skip_refine path.

Split from test_advance_skip.py: covers the operator-asserted refine skip-phase
hop (``refining-idea -> refined-idea`` for issue/epic, or ``refining-plan ->
planned`` for epic, routed by current status).
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from yoke_core.domain import advance_skip
from yoke_core.domain import advance_skip_finalize
from runtime.api.advance_skip_test_helpers import (
    _CallRecorder,
    _enter_all,
    _exit_all,
    _patch_core,
)
from runtime.api.test_backlog import (
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,  # noqa: F401 — fixture re-export
)


# ---------------------------------------------------------------------------
# skip_refine — happy path
# ---------------------------------------------------------------------------


class TestSkipRefineHappyPath:
    def test_idea_to_refined_idea_issue(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("idea", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_refine(199, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == [
            "refining-idea",
            "refined-idea",
        ]
        assert exec_recorder.rebuild_board_seen == [False, True]
        assert result["to_status"] == "refined-idea"
        assert result["skipped_phase"] == "refining-idea"

    def test_refining_idea_to_refined_idea_issue(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("refining-idea", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_refine(200, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == ["refined-idea"]
        assert result["via"] == "skip-refine"
        assert result["from_status"] == "refining-idea"
        assert result["to_status"] == "refined-idea"
        assert result["skipped_phase"] == "refining-idea"

    def test_refining_idea_to_refined_idea_epic(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("refining-idea", "epic", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_refine(201, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == ["refined-idea"]
        assert result["to_status"] == "refined-idea"

    def test_refining_plan_to_planned_epic(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("refining-plan", "epic", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_refine(202, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == ["planned"]
        assert result["from_status"] == "refining-plan"
        assert result["to_status"] == "planned"
        assert result["skipped_phase"] == "refining-plan"

    def test_plan_drafted_to_planned_epic(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("plan-drafted", "epic", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_refine(202, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == [
            "refining-plan",
            "planned",
        ]
        assert exec_recorder.rebuild_board_seen == [False, True]
        assert result["from_status"] == "plan-drafted"
        assert result["to_status"] == "planned"
        assert result["skipped_phase"] == "refining-plan"

    def test_bypass_reason_is_skip_refine(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("refining-idea", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            advance_skip.skip_refine(203, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert exec_recorder.bypass_seen == ["skip-refine"]
        assert exec_recorder.source_seen == ["skip-refine"]

    def test_claim_release_uses_finalize_exit(self):
        seen_reasons = []

        def fake_release(item_id, *, reason, session_id, out):
            seen_reasons.append(reason)
            return {"released": False, "reason": "no_active_claim"}

        patches = _patch_core(
            "refining-idea", "issue", release_recorder=fake_release
        )
        _enter_all(patches)
        try:
            advance_skip.skip_refine(204, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert seen_reasons == ["finalize-exit"]


# ---------------------------------------------------------------------------
# skip_refine — invalid-status and invalid-type rejection
# ---------------------------------------------------------------------------


class TestSkipRefineRejection:
    @pytest.mark.parametrize(
        "bad_status",
        [
            "refined-idea",
            "planning",
            "planned",
            "implementing",
            "reviewing-implementation",
            "reviewed-implementation",
            "implemented",
            "done",
        ],
    )
    def test_rejects_non_refining_status(self, bad_status):
        patches = _patch_core(bad_status, "epic")
        _enter_all(patches)
        try:
            with pytest.raises(ValueError, match="refining"):
                advance_skip.skip_refine(300, out=io.StringIO())
        finally:
            _exit_all(patches)

    def test_refining_plan_rejected_for_issue_type(self):
        """refining-plan is an epic-only status."""
        patches = _patch_core("refining-plan", "issue")
        _enter_all(patches)
        try:
            with pytest.raises(ValueError, match="epic"):
                advance_skip.skip_refine(301, out=io.StringIO())
        finally:
            _exit_all(patches)

    def test_plan_drafted_rejected_for_issue_type(self):
        """plan-drafted is an epic-only skip-refine entry."""
        patches = _patch_core("plan-drafted", "issue")
        _enter_all(patches)
        try:
            with pytest.raises(ValueError, match="epic"):
                advance_skip.skip_refine(302, out=io.StringIO())
        finally:
            _exit_all(patches)


# ---------------------------------------------------------------------------
# Integration: real backlog.execute_update path for skip_refine
# ---------------------------------------------------------------------------


def test_real_execute_update_path_refine(tmp_db):
    """Exercise the real backlog.execute_update seam for skip_refine."""
    _seed_item(
        tmp_db,
        id=991,
        type="issue",
        status="refining-idea",
        project="yoke",
    )

    with _patch_externals(), \
         mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}, clear=False), \
         mock.patch.object(
             advance_skip_finalize,
             "_emit_skip_event",
             lambda *a, **kw: None,
         ), \
         mock.patch.object(
             advance_skip_finalize,
             "_release_claim",
             lambda *a, **kw: {"released": False, "reason": "no_active_claim"},
         ):
        result = advance_skip.skip_refine(991, out=io.StringIO())

    assert result["to_status"] == "refined-idea"
    assert _item_field(tmp_db, 991, "status") == "refined-idea"
