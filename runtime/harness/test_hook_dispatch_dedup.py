"""One lifecycle event delivered twice runs the chain once; tool events never.

Claude Desktop drove ``SessionStart`` from two driver processes for a single
conversation. The second delivery must collapse. A second ``PreToolUse`` is a
second tool call to police and must always run.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.project_scratch_roots import ENV_KEY
from yoke_core.hooks.dispatch_dedup import duplicate_lifecycle_dispatch


PAYLOAD = '{"session_id":"s-1","hook_event_name":"SessionStart"}'


@pytest.fixture()
def scratch_root(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_KEY, str(tmp_path))
    return tmp_path


def _dispatch(event_name: str, *, stdin_data: str = PAYLOAD) -> bool:
    return duplicate_lifecycle_dispatch(
        event_name,
        session_id="s-1",
        stdin_data=stdin_data,
        run_half="local",
    )


def test_doubled_session_start_collapses_after_the_first_dispatch(scratch_root):
    assert _dispatch("SessionStart") is False
    assert _dispatch("SessionStart") is True


def test_doubled_pre_tool_use_always_dispatches(scratch_root):
    assert _dispatch("PreToolUse") is False
    assert _dispatch("PreToolUse") is False


def test_a_different_payload_is_a_different_dispatch(scratch_root):
    assert _dispatch("SessionStart") is False
    assert _dispatch("SessionStart", stdin_data=PAYLOAD + " ") is False
