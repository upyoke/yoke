"""The session resume block is its own server chain policy.

``yoke_core.hooks.session_resume_block`` renders and clears a reactivated
session's pending resume notice on the session-opening events, on the reply
channel the harness reads: raw stdout for Claude and Codex, the structured
``additionalContext`` envelope for Cursor. ``session_dispatch`` no longer
renders the block itself.
"""

from __future__ import annotations

from unittest import mock

import pytest
from yoke_contracts.hook_runner.chain_registry import chain_for

from yoke_core.hooks import session_dispatch, session_resume_block
from yoke_core.hooks.types import HookContext, Next, Outcome

_BLOCK = "> Your claims were released while you were away.\n"
_POLICY = "yoke_core.hooks.session_resume_block"
_DISPATCH = "yoke_core.hooks.session_dispatch"


def _context(family: str, event: str = "SessionStart", sid: str | None = "sess-r"):
    return HookContext(
        event_name=event,
        executor_family=family,
        executor_surface=family,
        payload={"session_id": sid} if sid else {},
        session_id=sid,
    )


def _evaluate(context: HookContext, block: str = _BLOCK):
    conn = mock.MagicMock()
    with (
        mock.patch("yoke_core.domain.db_helpers.connect", return_value=conn),
        mock.patch(
            "yoke_core.domain.sessions_resume_block.render_and_mark",
            return_value=block,
        ) as render,
    ):
        decision = session_resume_block.evaluate(context)
    return decision, render, conn


@pytest.mark.parametrize("family", ["claude", "codex"])
@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_raw_stdout_harnesses_receive_the_block_on_stdout(family, event) -> None:
    decision, render, conn = _evaluate(_context(family, event))

    assert decision.outcome is Outcome.AUDIT_ONLY
    assert decision.next is Next.CONTINUE
    assert decision.audit_fields == {"stdout": _BLOCK}
    render.assert_called_once_with(conn, "sess-r", harness_event=event)
    conn.close.assert_called_once()


def test_cursor_receives_the_block_as_additional_context() -> None:
    decision, _render, _conn = _evaluate(_context("cursor"))

    assert decision.outcome is Outcome.AUDIT_ONLY
    assert decision.audit_fields == {"additionalContext": _BLOCK}


def test_no_pending_notice_is_a_noop() -> None:
    decision, render, _conn = _evaluate(_context("claude"), block="")

    assert decision.outcome is Outcome.NOOP
    assert decision.audit_fields == {}
    render.assert_called_once()


@pytest.mark.parametrize("sid", [None, "", "unknown"])
def test_no_session_is_a_noop_without_db(sid) -> None:
    decision, render, _conn = _evaluate(_context("claude", sid=sid))

    assert decision.outcome is Outcome.NOOP
    render.assert_not_called()


def test_non_opening_event_is_a_noop_without_db() -> None:
    decision, render, _conn = _evaluate(_context("claude", event="Stop"))

    assert decision.outcome is Outcome.NOOP
    render.assert_not_called()


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit"])
def test_chain_runs_the_block_right_after_session_dispatch(event) -> None:
    chain = chain_for(event)

    assert chain.index(_POLICY) == chain.index(_DISPATCH) + 1


def test_codex_resumed_thread_session_start_renders_nothing_in_dispatch() -> None:
    """An already-armed Codex start marker leaves the block to the policy."""
    ctx = _context("codex")
    with (
        mock.patch(
            "yoke_core.hooks.codex_payload.resolve_session_id",
            return_value="sess-r",
        ),
        mock.patch("yoke_core.hooks.codex_payload.write_runtime_cache"),
        mock.patch(
            "yoke_core.hooks.codex_payload.session_marker_path",
            return_value="/nonexistent/marker",
        ),
        mock.patch(
            "yoke_core.hooks.codex_payload.check_and_arm_marker",
            return_value=False,
        ),
        mock.patch.dict("os.environ", {}, clear=False),
    ):
        stdout = session_dispatch._run_codex_session_start(ctx, "/repo")

    assert stdout == ""
