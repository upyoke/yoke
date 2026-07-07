"""Pytest suite for ``yoke_core.domain.advance_skip`` — skip_polish path.

Covers the operator-asserted skip-polish hop (``reviewed-implementation ->
implemented``, traversing ``polishing-implementation``), the safety guard,
constants, and the CLI surface. The skip_refine path lives in
``test_advance_skip_refine.py``.

Focus areas: happy path, invalid-status rejection, bypass scoping, event
emission shape, claim release routing.
"""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from yoke_core.domain import advance_skip, advance_skip_core
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
# skip_polish — happy path
# ---------------------------------------------------------------------------


class TestSkipPolishHappyPath:
    def test_writes_transit_and_end(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("reviewed-implementation", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            result = advance_skip.skip_polish(42, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == [
            "polishing-implementation",
            "implemented",
        ]
        assert result["via"] == "skip-polish"
        assert result["from_status"] == "reviewed-implementation"
        assert result["to_status"] == "implemented"
        assert result["skipped_phase"] == "polishing-implementation"
        assert result["hops_written"] == [
            "polishing-implementation",
            "implemented",
        ]

    def test_bypass_set_during_hops(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("reviewed-implementation", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            advance_skip.skip_polish(43, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert all(v == "skip-polish" for v in exec_recorder.bypass_seen)
        assert all(v == "skip-polish" for v in exec_recorder.source_seen)
        assert len(exec_recorder.bypass_seen) == 2

    def test_bypass_restored_after_hops(self):
        os.environ.pop("YOKE_CLAIM_BYPASS", None)
        os.environ.pop("YOKE_STATUS_SOURCE", None)
        patches = _patch_core("reviewed-implementation", "issue")
        _enter_all(patches)
        try:
            advance_skip.skip_polish(44, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert os.environ.get("YOKE_CLAIM_BYPASS", "") == ""
        assert os.environ.get("YOKE_STATUS_SOURCE", "") == ""

    def test_board_rebuild_only_happens_on_final_hop(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core("reviewed-implementation", "issue", executor=exec_recorder)
        _enter_all(patches)
        try:
            advance_skip.skip_polish(44, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert exec_recorder.rebuild_board_seen == [False, True]

    def test_claim_released_with_handoff_to_usher(self):
        seen_reasons = []

        def fake_release(item_id, *, reason, session_id, out):
            seen_reasons.append(reason)
            return {"released": True, "reason": "released"}

        patches = _patch_core(
            "reviewed-implementation", "issue", release_recorder=fake_release
        )
        _enter_all(patches)
        try:
            result = advance_skip.skip_polish(
                45, session_id="sess-polish", out=io.StringIO()
            )
        finally:
            _exit_all(patches)

        assert seen_reasons == ["handoff-to-usher"]
        assert result["claim_release"]["released"] is True

    def test_epic_item_also_supported(self):
        exec_recorder = _CallRecorder()
        patches = _patch_core(
            "reviewed-implementation", "epic", executor=exec_recorder
        )
        _enter_all(patches)
        try:
            advance_skip.skip_polish(46, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert [s for _, s in exec_recorder.calls] == [
            "polishing-implementation",
            "implemented",
        ]

    def test_event_envelope_shape(self):
        captured_events: list[dict] = []

        def fake_emit(item_id, **kwargs):
            captured_events.append({"item_id": item_id, **kwargs})

        patches = _patch_core(
            "reviewed-implementation", "issue", emit_recorder=fake_emit
        )
        _enter_all(patches)
        try:
            advance_skip.skip_polish(47, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert len(captured_events) == 1
        event = captured_events[0]
        assert event["item_id"] == 47
        assert event["via"] == "skip-polish"
        assert event["from_status"] == "reviewed-implementation"
        assert event["to_status"] == "implemented"
        assert event["skipped_phase"] == "polishing-implementation"


# ---------------------------------------------------------------------------
# skip_polish — invalid-status rejection
# ---------------------------------------------------------------------------


class TestSkipPolishRejection:
    @pytest.mark.parametrize(
        "bad_status",
        [
            "idea",
            "refining-idea",
            "refined-idea",
            "implementing",
            "reviewing-implementation",
            "polishing-implementation",
            "implemented",
            "release",
            "done",
        ],
    )
    def test_rejects_non_reviewed_implementation(self, bad_status):
        patches = _patch_core(bad_status, "issue")
        _enter_all(patches)
        try:
            with pytest.raises(ValueError, match="reviewed-implementation"):
                advance_skip.skip_polish(100, out=io.StringIO())
        finally:
            _exit_all(patches)

    def test_bypass_restored_when_status_rejected(self):
        os.environ.pop("YOKE_CLAIM_BYPASS", None)
        patches = _patch_core("idea", "issue")
        _enter_all(patches)
        try:
            with pytest.raises(ValueError):
                advance_skip.skip_polish(101, out=io.StringIO())
        finally:
            _exit_all(patches)

        assert os.environ.get("YOKE_CLAIM_BYPASS", "") == ""


# ---------------------------------------------------------------------------
# Safety guard: narrow allowlist rejects out-of-band hops
# ---------------------------------------------------------------------------


class TestAllowlistGuard:
    def test_polish_allowlist_excludes_pre_impl(self):
        """The skip-polish allowlist must not overlap with pre-impl statuses."""
        from yoke_core.domain import lifecycle_progression

        overlap = (
            advance_skip._POLISH_TRANSIT_ALLOWED
            & lifecycle_progression.PRE_IMPLEMENTATION_STATUSES
        )
        assert overlap == frozenset()

    def test_refine_allowlist_only_targets(self):
        """The skip-refine allowlist includes only refine bookkeeping statuses."""
        assert advance_skip._REFINE_TARGETS_ALLOWED == frozenset(
            {"refining-idea", "refined-idea", "refining-plan", "planned"}
        )

    def test_walk_hops_rejects_out_of_allowlist(self):
        out = io.StringIO()
        with pytest.raises(ValueError, match="not in allowlist"):
            advance_skip._walk_hops(
                1,
                hops=["implementing"],  # not in any skip allowlist
                bypass_reason="skip-polish",
                allowlist=advance_skip._POLISH_TRANSIT_ALLOWED,
                out=out,
            )

    def test_bypass_restored_on_hop_failure(self):
        os.environ.pop("YOKE_CLAIM_BYPASS", None)
        os.environ.pop("YOKE_STATUS_SOURCE", None)

        def failing(item_id, status, out, *, rebuild_board=True):
            return {"success": False, "error": "simulated"}

        with mock.patch.object(
            advance_skip_core, "_lookup_item",
            return_value=("reviewed-implementation", "issue"),
        ), mock.patch.object(advance_skip_core, "_do_execute_update", failing):
            with pytest.raises(RuntimeError, match="simulated"):
                advance_skip.skip_polish(500, out=io.StringIO())

        assert os.environ.get("YOKE_CLAIM_BYPASS", "") == ""
        assert os.environ.get("YOKE_STATUS_SOURCE", "") == ""


# ---------------------------------------------------------------------------
# Constants and surfaces
# ---------------------------------------------------------------------------


class TestConstants:
    def test_bypass_reason_names(self):
        assert advance_skip.BYPASS_SKIP_POLISH == "skip-polish"
        assert advance_skip.BYPASS_SKIP_REFINE == "skip-refine"

    def test_distinct_from_advance_intermediate_hop(self):
        """Skip bypass reasons must differ from the pre-impl hop reason."""
        assert advance_skip.BYPASS_SKIP_POLISH != "advance-intermediate-hop"
        assert advance_skip.BYPASS_SKIP_REFINE != "advance-intermediate-hop"


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


class TestCli:
    def test_cli_polish_happy_path(self, capsys):
        patches = _patch_core("reviewed-implementation", "issue")
        _enter_all(patches)
        try:
            rc = advance_skip.main(["polish", "YOK-77"])
        finally:
            _exit_all(patches)

        assert rc == 0
        out = capsys.readouterr().out
        assert "skip-polish" in out
        assert "YOK-77" in out

    def test_cli_refine_happy_path(self, capsys):
        patches = _patch_core("refining-idea", "issue")
        _enter_all(patches)
        try:
            rc = advance_skip.main(["refine", "YOK-78"])
        finally:
            _exit_all(patches)

        assert rc == 0
        out = capsys.readouterr().out
        assert "skip-refine" in out

    def test_cli_rejects_invalid_status(self, capsys):
        patches = _patch_core("idea", "issue")
        _enter_all(patches)
        try:
            rc = advance_skip.main(["polish", "YOK-79"])
        finally:
            _exit_all(patches)

        assert rc == 1
        err = capsys.readouterr().err
        assert "reviewed-implementation" in err

    def test_cli_rejects_bad_item_id(self, capsys):
        rc = advance_skip.main(["polish", "not-a-number"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "invalid item id" in err

# ---------------------------------------------------------------------------
# Integration: real backlog.execute_update path for skip_polish
# ---------------------------------------------------------------------------


def test_real_execute_update_path_polish(tmp_db):
    """Exercise the real backlog.execute_update seam for skip_polish."""
    _seed_item(
        tmp_db,
        id=990,
        type="issue",
        status="reviewed-implementation",
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
        result = advance_skip.skip_polish(990, out=io.StringIO())

    assert result["to_status"] == "implemented"
    assert _item_field(tmp_db, 990, "status") == "implemented"
