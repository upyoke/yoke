"""Coverage for the PreToolUse heartbeat refresh hook.

The hook lives at :mod:`runtime.harness.hook_helpers_heartbeat`. Per
the FR-3 Option B contract it is telemetry-style: never blocks tool
execution, swallows every failure, and returns
``HookDecision(outcome=NOOP, next=CONTINUE)`` unconditionally.

The tests below cover:

* Unknown / empty session-id is a fast no-op (no harness_sessions read).
* Known session-id triggers ``sessions_lifecycle_registry.heartbeat``
  through the module's call site.
* ``SessionError`` raised by the heartbeat writer collapses to NOOP.
* Generic ``Exception`` from the heartbeat writer collapses to NOOP.
* Hook is wired into the universal PreToolUse chain via
  :data:`yoke_contracts.hook_runner.hook_ordering.HOOK_ORDERING`.
* AC-15: adapter render path (``agents_render_subagent_hooks``) reads
  ``HOOK_ORDERING`` purely structurally, so adding the helper to the
  chain propagates to every Bash-capable subagent with zero per-agent
  authoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


@pytest.fixture(autouse=True)
def _pin_local_transport(monkeypatch):
    # The heartbeat DB-write tests assume the local transport is the
    # authority; pin the gate so the machine's real https connection (if
    # any) does not divert _heartbeat_session to its remote-only early
    # return. The https-skip behavior is asserted explicitly below.
    from runtime.harness import hook_helpers_heartbeat

    monkeypatch.setattr(
        hook_helpers_heartbeat, "_relay_owns_session_authority", lambda: False,
    )


@pytest.fixture()
def base_context():
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude-code",
        payload={},
        tool_name="Bash",
        command_body="python3 -c 'print(1)'",
        cwd="/tmp",
        session_id=None,
        item_id=None,
        now=datetime.now(timezone.utc),
    )


def _evaluate(record: HookContext) -> HookDecision:
    from runtime.harness import hook_helpers_heartbeat
    return hook_helpers_heartbeat.evaluate(record)


def test_evaluate_unknown_session_no_db_touch(base_context):
    ctx = HookContext(
        **{**base_context.__dict__, "session_id": "unknown"},
    )
    with mock.patch(
        "runtime.harness.hook_helpers_heartbeat._heartbeat_session"
    ) as hb:
        decision = _evaluate(ctx)
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
    assert decision.block is False
    hb.assert_not_called()


def test_evaluate_empty_session_no_db_touch(base_context):
    ctx = HookContext(
        **{**base_context.__dict__, "session_id": ""},
    )
    with mock.patch(
        "runtime.harness.hook_helpers_heartbeat._heartbeat_session"
    ) as hb:
        decision = _evaluate(ctx)
    assert decision.outcome is Outcome.NOOP
    hb.assert_not_called()


def test_evaluate_known_session_calls_heartbeat(base_context):
    ctx = HookContext(
        **{**base_context.__dict__, "session_id": "abc-123"},
    )
    with mock.patch(
        "runtime.harness.hook_helpers_heartbeat._heartbeat_session"
    ) as hb:
        decision = _evaluate(ctx)
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
    hb.assert_called_once_with("abc-123", ctx)


def test_evaluate_heartbeat_exception_collapses_to_noop(base_context):
    """A raw exception from the writer never propagates."""
    ctx = HookContext(
        **{**base_context.__dict__, "session_id": "abc-123"},
    )
    with mock.patch(
        "runtime.harness.hook_helpers_heartbeat._heartbeat_session",
        side_effect=RuntimeError("kaboom"),
    ) as hb:
        decision = _evaluate(ctx)
    assert decision.outcome is Outcome.NOOP
    hb.assert_called_once_with("abc-123", ctx)


def test_heartbeat_session_session_error_swallowed():
    """SessionError from the registry writer must not raise out."""
    from yoke_core.domain.sessions import SessionError
    from runtime.harness import hook_helpers_heartbeat

    with mock.patch(
        "yoke_core.domain.db_backend.connect"
    ) as conn_factory, mock.patch(
        "yoke_core.domain.sessions_lifecycle_registry.heartbeat",
        side_effect=SessionError("NOT_FOUND", "no such session"),
    ):
        conn = mock.MagicMock()
        conn_factory.return_value = conn
        hook_helpers_heartbeat._heartbeat_session("dead-session", mock.MagicMock())
        conn_factory.assert_called_once()
        conn.close.assert_called_once()


def test_heartbeat_session_uses_backend_factory():
    """Heartbeat must not open data/yoke.db through raw sqlite3."""
    from runtime.harness import hook_helpers_heartbeat

    with mock.patch("yoke_core.domain.db_backend.connect") as conn_factory:
        conn_factory.side_effect = RuntimeError("no authority")
        hook_helpers_heartbeat._heartbeat_session("abc-123", mock.MagicMock())
    conn_factory.assert_called_once()


def test_heartbeat_session_skips_local_write_on_https(monkeypatch):
    """On https the session row is server-side; a client-side in-process
    call must not open a local DB connection."""
    from runtime.harness import hook_helpers_heartbeat

    monkeypatch.setattr(
        hook_helpers_heartbeat, "_relay_owns_session_authority", lambda: True,
    )
    with mock.patch("yoke_core.domain.db_backend.connect") as conn_factory:
        hook_helpers_heartbeat._heartbeat_session("abc-123", mock.MagicMock())
    conn_factory.assert_not_called()


def test_heartbeat_session_backfills_missing_session(base_context):
    """A missed SessionStart still becomes board-visible on tool activity."""
    from yoke_core.domain.sessions import SessionError
    from runtime.harness import hook_helpers_heartbeat

    conn = mock.MagicMock()
    with mock.patch(
        "yoke_core.domain.db_backend.connect",
        return_value=conn,
    ), mock.patch(
        "yoke_core.domain.sessions_lifecycle_registry.heartbeat",
        side_effect=SessionError("NOT_FOUND", "no such session"),
    ), mock.patch(
        "runtime.harness.hook_runner.session_lifecycle_client.register_harness_session",
    ) as register, mock.patch(
        "runtime.harness.hook_helpers_identity.detect_provider",
        return_value="anthropic",
    ), mock.patch(
        # Pinned like detect_provider above: the backfill re-detects the
        # entrypoint from ambient env, so an unpinned run inside a desktop
        # harness session would recompose executor as claude-desktop.
        "runtime.harness.hook_helpers_identity.detect_entrypoint",
        return_value=None,
    ):
        hook_helpers_heartbeat._heartbeat_session("missing-sid", base_context)

    register.assert_called_once()
    kwargs = register.call_args.kwargs
    assert kwargs["session_id"] == "missing-sid"
    assert kwargs["executor"] == "claude-code"
    assert kwargs["provider"] == "anthropic"
    assert kwargs["model"] == "unknown"
    assert kwargs["root"] == "/tmp"
    assert kwargs["entrypoint"] is None
    conn.close.assert_called_once()


def test_evaluate_decision_shape(base_context):
    """Decision is always NOOP/CONTINUE/block=False — never blocks."""
    ctx = HookContext(
        **{**base_context.__dict__, "session_id": "abc"},
    )
    with mock.patch(
        "runtime.harness.hook_helpers_heartbeat._heartbeat_session"
    ):
        decision = _evaluate(ctx)
    assert decision.outcome is Outcome.NOOP
    assert decision.next is Next.CONTINUE
    assert decision.block is False
    assert decision.message == ""


# ---------------------------------------------------------------------------
# AC-15 — wired into the universal PreToolUse chain
# ---------------------------------------------------------------------------


_HEARTBEAT_MODULE = "runtime.harness.hook_helpers_heartbeat"


def test_pretool_bash_chain_includes_heartbeat():
    from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
    chain = ordered_pipeline_for("PreToolUse", "Bash")
    assert _HEARTBEAT_MODULE in chain
    # Heartbeat must run after every deny-class lint so a refused tool
    # call does not stamp a fresh heartbeat (no false-positive activity).
    idx = chain.index(_HEARTBEAT_MODULE)
    for lint in (
        "yoke_core.domain.lint_destructive_git",
        "yoke_core.domain.lint_long_command_polling",
        "yoke_core.domain.lint_session_cwd",
        "yoke_core.domain.path_claim_bash_guard",
    ):
        assert lint in chain
        assert chain.index(lint) < idx
    # observe_pre stays the tail.
    assert chain.index("yoke_core.domain.observe_pre") > idx


@pytest.mark.parametrize("matcher", ["Edit", "Write", "Read", "apply_patch"])
def test_pretool_edit_write_read_chains_include_heartbeat(matcher: str):
    from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
    chain = ordered_pipeline_for("PreToolUse", matcher)
    assert _HEARTBEAT_MODULE in chain
    assert chain.index("yoke_core.domain.observe_pre") > chain.index(
        _HEARTBEAT_MODULE
    )


@pytest.mark.parametrize("matcher", ["Bash", "Agent", "_default", "Read", "Edit"])
def test_posttool_chains_include_heartbeat_before_telemetry(matcher: str):
    from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
    chain = ordered_pipeline_for("PostToolUse", matcher)
    assert _HEARTBEAT_MODULE in chain
    assert chain.index("yoke_core.domain.observe") > chain.index(_HEARTBEAT_MODULE)


def test_pretool_monitor_does_not_include_heartbeat():
    """Monitor is wake-driven; activity is the underlying Bash, not the wake."""
    from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
    chain = ordered_pipeline_for("PreToolUse", "Monitor")
    assert _HEARTBEAT_MODULE not in chain
