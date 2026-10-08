"""A composed report spends its delivery record only if it reaches the model."""

import pytest

from yoke_contracts.hook_context_compose import compose_hook_context
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
from yoke_core.hooks import session_message_delivery as delivery
from runtime.harness.session_message_delivery_test_helpers import FakePort, hook_context


@pytest.mark.parametrize("family", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("oversized", [False, True])
def test_byte_ceiling_omission_leaves_the_report_delivery_record_unspent(
    monkeypatch, family, oversized
):
    report = f"{REPORT_BEGIN}\n{'x' * (2000 if oversized else 10)}\n{REPORT_END}"
    port = FakePort(empty_lease=True, report=report)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(
        "yoke_core.hooks.fleet_watcher_presence.list_process_cmdlines", lambda: ()
    )
    monkeypatch.setattr(
        "yoke_contracts.hook_context_compose.inline_context_bytes_for_harness",
        lambda harness: 1000,
    )
    surface = {"claude": "claude-code", "codex": "codex-cli", "cursor": "cursor-cli"}[
        family
    ]
    decision = delivery.evaluate(hook_context("PostToolUse", family=family, surface=surface))
    # Sibling delivery has priority; composing may omit the report entirely.
    rendered = compose_hook_context(["delivery"], [], [report], harness_id=family)
    delivery.settle_after_render(
        [decision], rendered_text=rendered, denied=False, port=port
    )
    assert bool(port.confirmed_reports) is not oversized
    if oversized:
        assert REPORT_BEGIN not in rendered
        assert "byte ceiling" in rendered
        # No confirmation reaches the shared record: a watcher remains able
        # to claim and emit this same fingerprint.
        assert port.confirmed_reports == []


@pytest.mark.parametrize(
    "rendered,denied",
    [("", False), ("{}", False), (REPORT_BEGIN, True), ("{}" + REPORT_BEGIN, False)],
)
def test_absent_denied_or_malformed_report_never_confirms_delivery(
    monkeypatch, rendered, denied
):
    port = FakePort(empty_lease=True, report=f"{REPORT_BEGIN}\n{REPORT_END}")
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(
        "yoke_core.hooks.fleet_watcher_presence.list_process_cmdlines", lambda: ()
    )
    decision = delivery.evaluate(hook_context())
    delivery.settle_after_render(
        [decision], rendered_text=rendered, denied=denied, port=port
    )
    assert port.confirmed_reports == []
