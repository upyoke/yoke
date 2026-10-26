"""Acknowledgement follows exactly the admitted batch, on every harness."""

import re

import pytest

from yoke_contracts.hook_context_compose import compose_hook_context, delivered_message_ids
from yoke_core.hooks.session_message_rendering import render_lease
from yoke_core.hooks.session_message_delivery_port import LeasedSessionMessage, SessionMessageLease


@pytest.mark.parametrize("harness", ["claude-code", "codex", "cursor-cli"])
@pytest.mark.parametrize("size", [10, 10000])
def test_one_acknowledgement_names_only_admitted_messages(harness, size):
    ids = [f"{number:08d}-2222-4333-8444-555555555555" for number in range(3)]
    lease = SessionMessageLease(
        lease_id="batch",
        messages=tuple(LeasedSessionMessage(message_id=value, body="x" * size,
                                           sender_actor_id=1) for value in ids),
    )
    rendered, token = render_lease(lease, session_id="session")
    assert rendered.count("Acknowledge:") == 1
    body = compose_hook_context([rendered], [], [], harness_id=harness)
    commands = re.findall(r"^Acknowledge: yoke messages acknowledge (.*)$", body, re.M)
    admitted = delivered_message_ids(body, token)
    assert len(commands) == 1
    assert set(commands[0].split()) == admitted
    assert admitted <= set(ids)
    assert admitted
