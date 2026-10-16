"""An empty message inbox that still owes a steering session its report.

``session_message_delivery.evaluate`` used to decline outright whenever
nothing was queued, even when a fleet report was independently owed — so a
steering session with an empty inbox never saw its report at model-visible
hook boundaries. These tests cover the report-only reply that fixes that.
"""

from __future__ import annotations

from yoke_contracts.hook_context_compose import FLEET_REPORT_CONTEXT_FIELD
from yoke_core.hooks import session_message_delivery as delivery
from yoke_core.hooks.types import Outcome
from runtime.harness.session_message_delivery_test_helpers import (
    REPORT_CLAIMED_AT,
    REPORT_FINGERPRINT,
    REPORT_NOT_AFTER,
    FakePort,
    hook_context,
)


_REPORT = "=== BEGIN YOKE FLEET REPORT ===\ndigest\n=== END YOKE FLEET REPORT ==="


def test_empty_inbox_with_a_report_attaches_it_on_the_stdout_channel(
    monkeypatch,
) -> None:
    port = FakePort(empty_lease=True, report=_REPORT)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(hook_context("SessionStart"))

    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["output_field"] == "stdout"
    assert audit["lease_id"] == ""
    assert audit["render_token"] == ""
    assert audit["report_fingerprint"] == REPORT_FINGERPRINT
    assert audit["report_claimed_at"] == REPORT_CLAIMED_AT
    assert audit["report_not_after"] == REPORT_NOT_AFTER
    assert "FLEET REPORT" in audit["rendered_text"]
    assert "SESSION MESSAGE DELIVERY" not in audit["rendered_text"]
    assert FLEET_REPORT_CONTEXT_FIELD not in decision.audit_fields
    # The empty-inbox telemetry for the (real, if empty) message lease still
    # fires; a report is a separate question from whether messages exist.
    assert port.completed == [("lease-1", False, "empty_lease")]


def test_empty_inbox_with_a_report_attaches_it_on_the_additional_context_channel(
    monkeypatch,
) -> None:
    port = FakePort(empty_lease=True, report=_REPORT)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(hook_context("PreToolUse"))

    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["output_field"] == "additionalContext"
    assert audit["rendered_text"] == ""
    assert decision.audit_fields[FLEET_REPORT_CONTEXT_FIELD] == _REPORT


def test_no_lease_at_all_still_attaches_an_owed_report(monkeypatch) -> None:
    """Mirrors the real port: a domain lease of ``None`` (nothing queued or
    eligible) does not preclude a report owed independently of any message."""
    port = FakePort(acknowledged=True, report=_REPORT)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(hook_context("SessionStart"))

    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["report_fingerprint"] == REPORT_FINGERPRINT
    assert "FLEET REPORT" in audit["rendered_text"]
    # No real lease existed to complete.
    assert port.completed == []


def test_empty_inbox_with_no_report_still_declines(monkeypatch) -> None:
    port = FakePort(empty_lease=True)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(hook_context("SessionStart"))

    assert decision.outcome is Outcome.NOOP
    assert port.completed == [("lease-1", False, "empty_lease")]


def test_a_pending_message_still_wins_over_the_hollow_report_only_path(
    monkeypatch,
) -> None:
    """A non-empty inbox never reaches the report-only branch; the message
    and its report keep composing together exactly as ``_decision_for_event``
    already does."""
    port = FakePort(report=_REPORT)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)

    decision = delivery.evaluate(hook_context("SessionStart"))

    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert audit["lease_id"] == "lease-1"
    assert "SESSION MESSAGE DELIVERY" in audit["rendered_text"]
    assert "FLEET REPORT" in audit["rendered_text"]
