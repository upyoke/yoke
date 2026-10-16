"""Report delivery adds a separate fleet-watcher alert the client proved owed."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from yoke_contracts.fleet_watcher_observation import FLEET_WATCHER_OBSERVATION_KEY
from yoke_contracts.hook_context_compose import (
    ALERT_BEGIN,
    FLEET_REPORT_CONTEXT_FIELD,
    FLEET_WATCHER_ALERT_CONTEXT_FIELD,
    REPORT_OMITTED_NOTICE,
    compose_context_list,
)
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_core.hooks import fleet_watcher_presence as presence
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.hook_context_compose import composed_additional_context
from yoke_core.hooks.session_message_delivery_port import SessionMessageLease
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
REARM = "`yoke watch fleet --print-streaming-pair -- --project yoke`"


def observed(live: bool, session_id: str = SESSION) -> dict:
    return {FLEET_WATCHER_OBSERVATION_KEY: {"session_id": session_id, "live": live}}


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


def _evaluate(monkeypatch, family, surface, payload, *, report=REPORT, remote=False):
    monkeypatch.setattr(delivery, "_delivery_port", lambda: ReportPort(report=report))
    context = replace(
        hook_context("PreToolUse", family=family, surface=surface, payload=payload),
        remote=remote,
    )
    return delivery.evaluate(context)


@pytest.mark.parametrize("remote", [False, True])
def test_proven_absence_rides_its_own_block_beside_the_report(monkeypatch, remote):
    decision = _evaluate(
        monkeypatch, "claude", "claude-cli", observed(False), remote=remote
    )

    assert decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD] == REPORT
    alert = decision.audit_fields[FLEET_WATCHER_ALERT_CONTEXT_FIELD]
    assert alert.startswith(ALERT_BEGIN)
    assert f"re-arm with {REARM}." in alert
    assert "native subscription its wait_mode declares" in alert


@pytest.mark.parametrize(
    "payload",
    [observed(True), {}, observed(False, session_id="someone-else")],
    ids=["live", "unobserved", "other-session"],
)
def test_no_alert_without_proven_absence(monkeypatch, payload):
    decision = _evaluate(monkeypatch, "claude", "claude-cli", payload)

    assert decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD] == REPORT
    assert FLEET_WATCHER_ALERT_CONTEXT_FIELD not in decision.audit_fields


def test_codex_stdout_channel_folds_the_alert_into_one_block(monkeypatch):
    context = hook_context(
        "SessionStart", family="codex", surface="codex-cli", payload=observed(False)
    )
    monkeypatch.setattr(delivery, "_delivery_port", lambda: ReportPort())
    decision = delivery.evaluate(context)

    rendered = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]["rendered_text"]
    assert rendered.index(ALERT_BEGIN) < rendered.index("BEGIN YOKE FLEET REPORT")
    assert "exec_command/write_stdin" in rendered
    assert "ended desktop turn has no native background notification" in rendered


def test_turn_start_without_idle_wake_names_the_scheduled_reentry():
    report = presence.fleet_watcher_absent_nudge(REPORT, "codex", "UserPromptSubmit")
    assert "in-turn command" in report
    assert "`keep steering`" in report
    assert ".agents/skills/yoke/steer/watching.md" in report
    mid_turn = presence.fleet_watcher_absent_nudge(REPORT, "codex", "PostToolUse")
    assert "keep steering" not in mid_turn
    idle_wake = presence.fleet_watcher_absent_nudge(
        REPORT, "cursor", "UserPromptSubmit"
    )
    assert "keep steering" not in idle_wake and "in-turn" not in idle_wake


@pytest.mark.parametrize(
    "row",
    [
        {"mode": "parked", "quiet_reason": "operator paused steering"},
        {"mode": "steer", "ended_at": "2026-09-01T00:00:00Z"},
        {"mode": "steer", "terminated_at": "2026-09-01T00:00:00Z"},
        None,
    ],
    ids=["parked", "ended", "terminated", "unreadable"],
)
@pytest.mark.parametrize("family", ["claude", "codex", "cursor"])
def test_posture_suppresses_the_alert(monkeypatch, row, family):
    monkeypatch.setattr(presence, "_session_row", lambda _session: row)
    context = hook_context(family=family, payload=observed(False))
    assert presence.fleet_watcher_alert(REPORT, context) == ""


def test_failed_posture_read_stays_silent(monkeypatch):
    def boom(_session):
        raise RuntimeError("transport down")

    monkeypatch.setattr(presence, "_session_row", boom)
    assert (
        presence.fleet_watcher_alert(REPORT, hook_context(payload=observed(False)))
        == ""
    )


@pytest.mark.parametrize("mode", ["wait", "busy", "steer"])
def test_active_modes_alert(monkeypatch, mode):
    monkeypatch.setattr(presence, "_session_row", lambda _session: {"mode": mode})
    assert "re-arm" in presence.fleet_watcher_alert(
        REPORT, hook_context(payload=observed(False))
    )


def test_document_seats_rearm_once_per_distinct_project():
    report = "## project-a · FIRST\n## project-a · SECOND\n## project-b\n"
    nudge = presence.fleet_watcher_absent_nudge(report, "codex", "PostToolUse")
    assert "--project project-a --project project-b" in nudge
    assert nudge.count("--project project-a") == 1
    assert "FIRST" not in nudge and "SECOND" not in nudge


@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor"])
def test_byte_ceiling_drops_the_report_and_keeps_the_alert(harness):
    budget = inline_context_bytes_for_harness(harness)
    report = f"{REPORT}\n{'x' * budget}"
    alert = presence.fleet_watcher_absent_nudge(REPORT, harness, "PostToolUse")
    alert_block = f"{ALERT_BEGIN}\n{alert}\n=== END YOKE FLEET WATCHER ALERT ==="

    body = compose_context_list(["a hint", report, alert_block], harness_id=harness)

    assert alert_block in body
    assert REPORT_OMITTED_NOTICE in body
    assert "a hint" not in body and "x" * 50 not in body


def test_decision_composition_ranks_the_alert_above_hints_and_report(monkeypatch):
    decision = _evaluate(monkeypatch, "claude", "claude-cli", observed(False))
    hint = replace(decision, audit_fields={"additionalContext": "a hint"})

    body = composed_additional_context([hint, decision], harness_id="claude-code")

    assert body.index(ALERT_BEGIN) < body.index("a hint") < body.index("FLEET REPORT")
