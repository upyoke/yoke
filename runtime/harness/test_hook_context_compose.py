"""Ordered, capped hook-context composition."""

from __future__ import annotations

from yoke_contracts.hook_context_compose import (
    POINTER_BEGIN,
    compose_hook_context,
    overflow_lease_marker,
    render_overflow_pointer,
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
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {TOKEN} ===",
            f"--- BEGIN YOKE SESSION MESSAGE {MESSAGE_ID} ---",
            body,
            f"--- END YOKE SESSION MESSAGE {MESSAGE_ID} ---",
            f"=== END YOKE SESSION MESSAGE DELIVERY {TOKEN} ===",
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


def test_oversized_delivery_becomes_a_pointer_and_drops_the_lease_token() -> None:
    huge = _delivery("x" * 9000)
    body = compose_hook_context([huge], ["hint"], [], harness_id="claude-code")
    assert POINTER_BEGIN in body
    assert TOKEN not in body
    assert overflow_lease_marker(LEASE_ID) in body
    assert f"yoke messages get {MESSAGE_ID}" in body
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
                "=== BEGIN YOKE FLEET REPORT ===\n"
                "digest\n"
                "=== END YOKE FLEET REPORT ==="
            )
        },
        next=Next.CONTINUE,
    )
    body = composed_additional_context([report, delivery], harness_id="claude-code")
    assert body.index("SESSION MESSAGE DELIVERY") < body.index("FLEET REPORT")


def test_overflow_pointer_never_contains_the_injection_token() -> None:
    pointer = render_overflow_pointer(_delivery("x" * 100))
    assert TOKEN not in pointer
    assert overflow_lease_marker(LEASE_ID) in pointer
    assert POINTER_BEGIN in pointer


def test_oversized_report_is_omitted_before_a_fitting_delivery() -> None:
    huge = "=== BEGIN YOKE FLEET REPORT ===\n" + ("x" * 9000)
    body = compose_hook_context([_delivery()], [], [huge], harness_id="claude-code")
    assert TOKEN in body
    assert "BEGIN YOKE FLEET REPORT" not in body
    assert "omitted by the hook-context byte ceiling" in body


def test_oversized_launch_delivery_is_omitted_without_a_pointer() -> None:
    huge = "=== BEGIN YOKE LAUNCH DELIVERY ===\n" + ("x" * 9000)
    body = compose_hook_context([huge], ["hint"], [], harness_id="claude-code")
    assert POINTER_BEGIN not in body
    assert "BEGIN YOKE LAUNCH DELIVERY" not in body
    assert "hint" in body
