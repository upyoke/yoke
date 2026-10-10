"""Ordered, capped hook-context composition."""

from __future__ import annotations

from yoke_contracts.hook_context_compose import (
    compose_hook_context,
    render_message_stub,
)
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_core.hooks.types import HookDecision, Next, Outcome
from yoke_core.hooks.hook_context_compose import composed_additional_context
from yoke_core.hooks.decision_render import render_claude_decision


LEASE_ID = "lease-overflow"
TOKEN = f"YOKE_SESSION_MESSAGE_LEASE:{LEASE_ID}"
MESSAGE_ID = "11111111-2222-4333-8444-555555555555"


def _delivery(body: str = "hello") -> str:
    return "\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} {MESSAGE_ID} ===",
            body,
            "=== END YOKE SESSION MESSAGE DELIVERY ===",
        )
    )


def _advisory(text: str) -> HookDecision:
    return HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": text},
        next=Next.CONTINUE,
    )


def test_inline_ceilings_come_from_the_python_contract() -> None:
    assert inline_context_bytes_for_harness("claude-code") == 8192
    assert inline_context_bytes_for_harness("claude-desktop") == 8192
    assert inline_context_bytes_for_harness("codex") == 2500
    assert inline_context_bytes_for_harness("cursor-cli") == 8192


def test_delivery_leads_hints_and_report_even_when_chain_order_is_reversed() -> None:
    hint = "<system-reminder>hint first in the chain</system-reminder>"
    report = "=== BEGIN YOKE FLEET REPORT ===\nquiet\n=== END YOKE FLEET REPORT ==="
    body = compose_hook_context(
        [_delivery()],
        [hint],
        [report],
        harness_id="claude-code",
    )
    assert body.index("BEGIN YOKE SESSION MESSAGE DELIVERY") < body.index(hint)
    assert body.index(hint) < body.index("BEGIN YOKE FLEET REPORT")
    assert TOKEN in body


def test_oversized_delivery_becomes_an_injected_stub() -> None:
    huge = _delivery("x" * 9000)
    body = compose_hook_context([huge], ["hint"], [], harness_id="claude-code")
    assert "delivered as a stub" in body
    assert TOKEN in body
    assert f"yoke messages get {MESSAGE_ID}" in body
    assert f"yoke messages get {MESSAGE_ID} --json" not in body
    assert f"yoke messages acknowledge {MESSAGE_ID}" in body
    assert "hint" not in body
    assert len(body.encode("utf-8")) <= 8192


def test_codex_ceiling_drops_hints_before_a_fitting_delivery() -> None:
    delivery = _delivery("payload")
    hint = "h" * 3000
    body = compose_hook_context([delivery], [hint], [], harness_id="codex")
    assert TOKEN in body
    assert hint not in body
    assert len(body.encode("utf-8")) <= 2500


def test_renderer_reorders_chain_order_into_delivery_then_hint() -> None:
    stdout, code = render_claude_decision(
        [_advisory("hint-before"), _advisory(_delivery("body"))],
        "PreToolUse",
    )
    assert code == 0
    assert "BEGIN YOKE SESSION MESSAGE DELIVERY" in stdout
    ctx_start = stdout.index("additionalContext")
    assert stdout.index(_delivery("body")[:40], ctx_start) < stdout.index(
        "hint-before", ctx_start
    )


def test_composed_additional_context_reads_fleet_report_field() -> None:
    delivery = HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields={"additionalContext": _delivery()},
        next=Next.CONTINUE,
    )
    report = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={
            "fleetReportContext": (
                "=== BEGIN YOKE FLEET REPORT ===\ndigest\n=== END YOKE FLEET REPORT ==="
            )
        },
        next=Next.CONTINUE,
    )
    body = composed_additional_context([report, delivery], harness_id="claude-code")
    assert body.index("SESSION MESSAGE DELIVERY") < body.index("FLEET REPORT")


def test_stub_carries_sender_and_bounded_first_line() -> None:
    message = "\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} {MESSAGE_ID} ===",
            "Authenticated sender: Ben via session sender",
            '| "First line ' + "x" * 9000 + '"',
            '| "second line must be read"',
            "=== END YOKE SESSION MESSAGE DELIVERY ===",
        )
    )
    stub = render_message_stub(message)
    assert "Ben via session sender" in stub
    assert "First line" in stub
    assert "second line" not in stub
    assert len(stub.encode()) < inline_context_bytes_for_harness("codex")


def test_oversized_report_is_omitted_before_a_fitting_delivery() -> None:
    huge = "=== BEGIN YOKE FLEET REPORT ===\n" + ("x" * 9000)
    body = compose_hook_context([_delivery()], [], [huge], harness_id="claude-code")
    assert TOKEN in body
    assert "BEGIN YOKE FLEET REPORT" not in body
    assert "omitted by the hook-context byte ceiling" in body


def test_oversized_launch_delivery_is_omitted_without_a_message_stub() -> None:
    huge = "=== BEGIN YOKE LAUNCH DELIVERY ===\n" + ("x" * 9000)
    body = compose_hook_context([huge], ["hint"], [], harness_id="claude-code")
    assert "delivered as a stub" not in body
    assert "BEGIN YOKE LAUNCH DELIVERY" not in body
    assert "hint" in body


SMALL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
HUGE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_fitting_messages_ship_with_an_oversized_sibling_stub() -> None:
    block = "\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} {SMALL_ID} ===",
            "hello",
            "=== END YOKE SESSION MESSAGE DELIVERY ===",
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} {HUGE_ID} ===",
            "x" * 9000,
            "=== END YOKE SESSION MESSAGE DELIVERY ===",
        )
    )
    body = compose_hook_context([block], [], [], harness_id="claude-code")
    assert f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} {SMALL_ID} ===" in body
    assert "hello" in body
    assert "delivered as a stub" in body
    assert f"Read the full body: yoke messages get {HUGE_ID}" in body
    assert "x" * 9000 not in body


def test_an_under_cap_delivery_is_unchanged() -> None:
    delivery = _delivery("unchanged body")
    assert compose_hook_context([delivery], [], [], harness_id="codex") == delivery


def test_non_ascii_stub_previews_fit_the_smallest_harness_budget() -> None:
    import json
    from yoke_core.hooks.session_message_rendering import render_lease
    from yoke_core.hooks.session_message_delivery_port import (
        LeasedSessionMessage,
        SessionMessageLease,
    )

    for character in ("😀", "\u0001", "-", "\u2028"):
        lease = SessionMessageLease(
            lease_id=LEASE_ID,
            messages=(
                LeasedSessionMessage(
                    message_id=MESSAGE_ID,
                    body=character * 9000,
                    sender_actor_id=1,
                    sender_actor_label=character * 9000,
                ),
            ),
        )
        rendered, _ = render_lease(lease, session_id="session")
        body = compose_hook_context([rendered], [], [], harness_id="codex")
        assert "delivered as a stub" in body
        assert TOKEN in body
        assert len(body.encode()) <= inline_context_bytes_for_harness("codex")
        preview = next(line[2:] for line in body.splitlines() if line.startswith("| "))
        assert json.loads(preview).startswith(character)
