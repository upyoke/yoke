"""Hook injection appends a one-line fleet-watcher nudge when it is missing."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from yoke_contracts.hook_context_compose import FLEET_REPORT_CONTEXT_FIELD
from yoke_core.hooks import fleet_watcher_presence as presence
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.session_message_delivery_port import SessionMessageLease
from yoke_core.tools import watch_fleet
from runtime.harness.session_message_delivery_test_helpers import (
    FakePort,
    hook_context,
)


REPORT = (
    "=== BEGIN YOKE FLEET REPORT ===\n"
    "composed 2026-09-01T00:00:00Z · 1 held scopes\n"
    "## yoke\n"
    "available: none\n"
    "=== END YOKE FLEET REPORT ==="
)
SESSION = "session-top"
CAPTURE = (
    f"/scratch/yoke/sessions/{SESSION}/runs/pid-9/"
    "watcher-captures/yoke-fleet.raw.abc.log"
)
WATCHER_CMDLINES = (
    f"python3 -m {presence.PROBE_MODULE} --project yoke",
    f"python3 -m {presence.WRAPPER_MODULE} --raw-capture {CAPTURE} -- --project yoke",
)
UNRELATED_CMDLINES = ("zsh", "cursor", "python3 -m pytest")


@dataclass
class ReportPort(FakePort):
    """Lease the parent envelope with a composed fleet report attached."""

    report: str = REPORT

    def lease_for_hook(self, **kwargs: object) -> SessionMessageLease | None:
        lease = super().lease_for_hook(**kwargs)
        if lease is None:
            return None
        return replace(lease, report=self.report)


@pytest.fixture(autouse=True)
def active_steering_session(monkeypatch):
    monkeypatch.setattr(presence, "_session_row", lambda _session: {"mode": "steer"})


def test_detection_tokens_match_the_live_watcher_wrapper() -> None:
    assert presence.PROBE_MODULE == watch_fleet.PROBE_MODULE
    assert presence.WRAPPER_MODULE == watch_fleet.WRAPPER_MODULE
    assert presence.CAPTURE_KIND == watch_fleet.KIND


def test_report_injection_with_no_watcher_appends_the_nudge_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = ReportPort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(presence, "list_process_cmdlines", lambda: UNRELATED_CMDLINES)

    decision = delivery.evaluate(
        hook_context("PreToolUse", family="claude", surface="claude-cli")
    )

    report = decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD]
    assert REPORT in report
    assert "YOKE FLEET REPORT" not in decision.audit_fields["additionalContext"]
    nudge_lines = [
        line
        for line in report.splitlines()
        if line.startswith("Fleet watcher is not running for this session")
    ]
    assert nudge_lines == [
        "Fleet watcher is not running for this session; re-arm with "
        "`yoke watch fleet --print-streaming-pair -- --project yoke`."
        " Follow the returned wait_mode; use only its declared native subscription."
    ]


def test_report_injection_with_a_live_watcher_does_not_append_the_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = ReportPort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(presence, "list_process_cmdlines", lambda: WATCHER_CMDLINES)

    decision = delivery.evaluate(
        hook_context("PreToolUse", family="claude", surface="claude-cli")
    )

    report = decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD]
    assert REPORT in report
    assert "YOKE FLEET REPORT" not in decision.audit_fields["additionalContext"]
    assert "Fleet watcher is not running" not in report


def test_codex_nudge_names_the_active_tool_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = ReportPort()
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(presence, "list_process_cmdlines", lambda: UNRELATED_CMDLINES)

    decision = delivery.evaluate(
        hook_context("PreToolUse", family="codex", surface="codex-cli")
    )

    report = decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD]
    assert REPORT in report
    assert "YOKE FLEET REPORT" not in decision.audit_fields["additionalContext"]
    assert "Fleet watcher is not running" in report
    assert "exec_command/write_stdin" in report
    assert "commentary" in report
    assert "ended desktop turn has no native background notification" in report
    assert presence.list_process_cmdlines() == UNRELATED_CMDLINES


def test_cursor_family_nudges_when_the_watcher_is_absent() -> None:
    nudged = presence.maybe_append_fleet_watcher_nudge(
        REPORT,
        session_id=SESSION,
        executor_family="cursor",
        remote=False,
        cmdlines=UNRELATED_CMDLINES,
    )
    assert nudged.endswith(
        "Fleet watcher is not running for this session; re-arm with "
        "`yoke watch fleet --print-streaming-pair -- --project yoke`."
        " Follow the returned wait_mode; use only its declared native subscription."
    )


def test_remote_evaluation_does_not_invent_a_local_gap() -> None:
    assert (
        presence.maybe_append_fleet_watcher_nudge(
            REPORT,
            session_id=SESSION,
            executor_family="claude",
            remote=True,
            cmdlines=UNRELATED_CMDLINES,
        )
        == REPORT
    )


@pytest.mark.parametrize("family", ["claude", "codex", "cursor"])
def test_pause_suppresses_rearm_until_explicit_resume(monkeypatch, family):
    row = {"mode": "parked", "quiet_reason": "operator paused steering"}
    monkeypatch.setattr(presence, "_session_row", lambda _session: row)
    kwargs = dict(
        session_id=SESSION,
        executor_family=family,
        remote=False,
        cmdlines=UNRELATED_CMDLINES,
    )
    assert presence.maybe_append_fleet_watcher_nudge(REPORT, **kwargs) == REPORT
    row["mode"] = "steer"
    assert "re-arm" in presence.maybe_append_fleet_watcher_nudge(REPORT, **kwargs)


def test_document_seats_rearm_once_per_distinct_project():
    report = "## project-a · FIRST\n## project-a · SECOND\n## project-b\n"
    nudge = presence.fleet_watcher_absent_nudge(report, "codex")
    assert "--project project-a --project project-b" in nudge
    assert nudge.count("--project project-a") == 1
    assert "FIRST" not in nudge and "SECOND" not in nudge


def test_unreadable_posture_teaches_recovery_without_overriding_pause(monkeypatch):
    monkeypatch.setattr(presence, "_session_row", lambda _session: None)
    report = presence.maybe_append_fleet_watcher_nudge(
        REPORT,
        session_id=SESSION,
        executor_family="codex",
        remote=False,
        cmdlines=UNRELATED_CMDLINES,
    )
    assert "posture is unreadable" in report
    assert "preserving an explicit parked/stop request" in report
    assert "yoke sessions list --json" in report
