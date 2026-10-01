"""Close-out refusal notices stay useful within every harness inline cap."""

from __future__ import annotations

import pytest

from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_core.domain.deployment_close_out_failure_summary import (
    close_out_failure_summary,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_message,
)
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_message,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER, STEERING


@pytest.mark.parametrize(
    "message", [item_qa_accepted_message, delivery_cleared_message]
)
@pytest.mark.parametrize("route", [HOLDER, STEERING])
def test_three_requirement_failure_is_compact_and_names_the_gate(
    message, route
) -> None:
    public_ref = "TEST-" + str(24)
    refusal = "3 blocking QA requirement(s) unsatisfied.\n" + "\n".join(
        f"  - Requirement #{value} (command, phase=post_deploy): no passing run "
        + "detail " * 500
        for value in (101, 102, 103)
    )
    body = message(
        public_ref=public_ref,
        run_id="run-notice",
        route=route,
        close_out_failure=refusal,
    )
    assert "#101, #102, #103" in body
    assert f"yoke qa gate-summary --item {public_ref} --target implemented" in body
    assert "detail" not in body
    assert len(body.encode()) < inline_context_bytes_for_harness("codex")


def test_non_requirement_failure_still_names_a_read() -> None:
    public_ref = "TEST-" + str(25)
    summary = close_out_failure_summary(public_ref, "unreadable gate " * 500)
    assert "Automatic close-out failed" in summary
    assert public_ref in summary
    assert "unreadable" not in summary
