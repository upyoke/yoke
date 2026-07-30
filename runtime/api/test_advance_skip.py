# ruff: noqa: F811
"""Skip-polish behavior, bypass scoping, events, claims, and CLI coverage."""

from __future__ import annotations

import io
import os
from unittest import mock

import pytest

from yoke_core.domain import advance_skip, advance_skip_core
from yoke_core.domain import advance_skip_finalize
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime
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
    def test_bypass_restored_on_hop_failure(self):
        os.environ.pop("YOKE_CLAIM_BYPASS", None)
        os.environ.pop("YOKE_STATUS_SOURCE", None)

        def failing(item_id, status, out, *, rebuild_board=True):
            return {"success": False, "error": "simulated"}

        with mock.patch.object(
            advance_skip_core, "_lookup_item",
            return_value=(
                "reviewed-implementation",
                builtin_workflow_runtime("issue"),
            ),
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
    def test_cli_polish_happy_path(self, tmp_db, capsys):
        _seed_item(tmp_db, id=77, workflow_id="issue", status="reviewed-implementation")
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

    def test_cli_refine_happy_path(self, tmp_db, capsys):
        _seed_item(tmp_db, id=78, workflow_id="issue", status="refining-idea")
        patches = _patch_core("refining-idea", "issue")
        _enter_all(patches)
        try:
            rc = advance_skip.main(["refine", "YOK-78"])
        finally:
            _exit_all(patches)

        assert rc == 0
        out = capsys.readouterr().out
        assert "skip-refine" in out

    def test_cli_prefix_ref_resolves_project_sequence(self, tmp_db, capsys):
        # Internal id deliberately diverges from the public ref: YOK-444 is
        # project_sequence 444 on internal id 500. A prefix-strip resolver
        # would act on internal id 444; the canonical parser targets 500.
        _seed_item(
            tmp_db,
            id=500,
            workflow_id="issue",
            status="reviewed-implementation",
            project_sequence=444,
        )
        exec_recorder = _CallRecorder()
        patches = _patch_core(
            "reviewed-implementation", "issue", executor=exec_recorder
        )
        _enter_all(patches)
        try:
            rc = advance_skip.main(["polish", "YOK-444"])
        finally:
            _exit_all(patches)

        assert rc == 0
        assert [i for i, _ in exec_recorder.calls] == [500, 500]

    def test_cli_rejects_invalid_status(self, tmp_db, capsys):
        _seed_item(tmp_db, id=79, workflow_id="issue", status="idea")
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
        workflow_id="issue",
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
