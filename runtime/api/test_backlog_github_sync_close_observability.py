"""Structured failure-event coverage for closing mirrored GitHub issues."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from unittest.mock import patch

from yoke_core.domain import backlog_rendering
from yoke_core.engines import done_transition_github_sync


class TestCloseIssueSyncFailedEmission:
    """Every failed issue-close path emits ``SyncFailed(operation="state")``."""

    def test_close_rc_nonzero_emits_sync_failed(self):
        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        out = io.StringIO()
        with patch.object(backlog_rendering, "_is_dry_run", return_value=False), patch(
            "yoke_core.domain.backlog_github_sync.close_issue", return_value=7,
        ), patch.object(
            backlog_rendering, "_record_sync_failure", side_effect=capture,
        ):
            ok = backlog_rendering._close_issue(73, out=out)

        assert ok is False
        assert recorded, "rc!=0 must emit SyncFailed(operation=state)"
        item_id, operation, reason = recorded[0]
        assert item_id == 73
        assert operation == "state"
        assert "rc=7" in reason

    def test_close_exception_emits_sync_failed(self):
        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        out = io.StringIO()
        with patch.object(backlog_rendering, "_is_dry_run", return_value=False), patch(
            "yoke_core.domain.backlog_github_sync.close_issue",
            side_effect=RuntimeError("transport blew up"),
        ), patch.object(
            backlog_rendering, "_record_sync_failure", side_effect=capture,
        ):
            ok = backlog_rendering._close_issue(74, out=out)

        assert ok is False
        assert recorded, "exception must emit SyncFailed(operation=state)"
        item_id, operation, reason = recorded[0]
        assert item_id == 74
        assert operation == "state"
        assert "transport blew up" in reason

    def test_close_success_emits_no_sync_failed(self):
        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        out = io.StringIO()
        with patch.object(backlog_rendering, "_is_dry_run", return_value=False), patch(
            "yoke_core.domain.backlog_github_sync.close_issue", return_value=0,
        ), patch.object(
            backlog_rendering, "_record_sync_failure", side_effect=capture,
        ):
            ok = backlog_rendering._close_issue(75, out=out)

        assert ok is True
        assert recorded == []

    def test_close_dry_run_emits_no_sync_failed(self):
        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        out = io.StringIO()
        with patch.object(backlog_rendering, "_is_dry_run", return_value=True), patch.object(
            backlog_rendering, "_record_sync_failure", side_effect=capture,
        ):
            ok = backlog_rendering._close_issue(76, out=out)

        assert ok is True
        assert recorded == []

    def test_done_transition_degraded_emits_sync_failed(self):
        @dataclass
        class _FakeResult:
            steps_completed: list = field(default_factory=list)
            warnings: list = field(default_factory=list)

            def add_step(self, step):
                self.steps_completed.append(step)

        recorded: list[tuple] = []

        def capture(item_id, operation, reason="unknown"):
            recorded.append((item_id, operation, reason))

        with patch.object(
            done_transition_github_sync,
            "run_step_8",
            return_value=done_transition_github_sync.Step8Result(
                returncode=1,
                step_marker="8-degraded",
                message="sync_done_item returned 1",
            ),
        ), patch.object(
            backlog_rendering, "_record_sync_failure", side_effect=capture,
        ):
            outcome = done_transition_github_sync.apply_step_8(
                77, "release", _FakeResult(),
            )

        assert outcome.is_degraded
        assert recorded, "degraded done sync must emit SyncFailed(operation=state)"
        item_id, operation, reason = recorded[0]
        assert item_id == 77
        assert operation == "state"
        assert "step 8 degraded" in reason
