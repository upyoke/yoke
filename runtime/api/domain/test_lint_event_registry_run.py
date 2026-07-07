"""lint_event_registry — emit_denial / evaluate / main canonical-fallback coverage.

Split out of ``test_lint_event_registry.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

import io
import json
from unittest import mock

from yoke_core.domain import lint_event_registry as lint_mod
from yoke_core.domain.lint_event_registry import (
    CHECK_ID,
    HOOK_NAME,
    Decision,
    HookMeta,
    build_deny_json,
    build_deny_reason,
    emit_denial,
    evaluate,
)
from yoke_core.domain.lint_event_registry_test_helpers import (  # noqa: F401 — fixtures
    _payload,
    registry_db,
)
from runtime.harness.hook_runner.types import Next, Outcome


def _record(payload_json: str):
    """Build a HookContext from a serialized payload as evaluate() expects."""
    data = json.loads(payload_json)
    return lint_mod._build_context_from_payload(data)


class TestEmitDenial:
    def test_allow_is_noop(self):
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event"
        ) as mocked:
            emit_denial(Decision(action="allow"))
        mocked.assert_not_called()

    def test_warn_is_noop(self):
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event"
        ) as mocked:
            emit_denial(Decision(action="warn", stderr_message="w"))
        mocked.assert_not_called()

    def test_deny_fires_event(self):
        decision = Decision(
            action="deny",
            event_name="Foo",
            deny_json=build_deny_json("Foo"),
            reason=build_deny_reason("Foo"),
            hook_meta=HookMeta(session_id="s", tool_use_id="t", turn_id="r"),
        )
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event"
        ) as mocked:
            emit_denial(decision)
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        assert kwargs["hook"] == HOOK_NAME
        assert kwargs["check_id"] == CHECK_ID
        assert kwargs["session_id"] == "s"
        assert kwargs["tool_use_id"] == "t"
        assert kwargs["turn_id"] == "r"
        assert "Foo" in kwargs["reason"]

    def test_emit_tolerates_backend_failure(self):
        decision = Decision(
            action="deny",
            event_name="Foo",
            deny_json=build_deny_json("Foo"),
            reason=build_deny_reason("Foo"),
        )
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event",
            side_effect=RuntimeError("backend down"),
        ):
            # Must not raise.
            emit_denial(decision)


class TestEvaluate:
    def test_allow_returns_noop_no_streams(self, registry_db, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", registry_db)
        decision = evaluate(_record(_payload('sh emit-event.sh --name "ActiveEvent"')))
        assert decision.outcome is Outcome.NOOP
        assert decision.next is Next.CONTINUE
        assert decision.message == ""
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_warn_writes_stderr_returns_warn(self, registry_db, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", registry_db)
        decision = evaluate(
            _record(_payload('sh emit-event.sh --name "DeprecatedEvent"'))
        )
        assert decision.outcome is Outcome.WARN
        assert decision.next is Next.CONTINUE
        assert decision.message == ""
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "DeprecatedEvent" in captured.err
        assert captured.err.startswith("WARN")

    def test_deny_carries_envelope_and_emits(self, registry_db, monkeypatch):
        monkeypatch.setenv("YOKE_DB", registry_db)
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event"
        ) as mocked:
            decision = evaluate(
                _record(
                    _payload(
                        'sh emit-event.sh --name "Unknown"',
                        session_id="sid",
                        tool_use_id="tu",
                    )
                )
            )
        assert decision.outcome is Outcome.DENY
        assert decision.next is Next.STOP
        assert decision.block is True
        assert '"permissionDecision": "deny"' in decision.message
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        assert kwargs["session_id"] == "sid"
        assert kwargs["tool_use_id"] == "tu"

    def test_empty_payload_returns_noop(self, registry_db, monkeypatch):
        monkeypatch.setenv("YOKE_DB", registry_db)
        ctx = lint_mod._build_context_from_payload({})
        decision = evaluate(ctx)
        assert decision.outcome is Outcome.NOOP


class TestYok1384CanonicalFallback:
    """``lint_event_registry.main()`` and :func:`evaluate` must resolve DB
    paths via the Python ``db_helpers.resolve_db_path`` fallback when
    ``YOKE_DB`` is unset.

    Prior to the tracked-launcher fix the Claude PreToolUse launcher injected
    the worktree-local DB path directly, silently bypassing the Python
    worktree-aware resolver from inside linked worktrees. The launcher now
    runs the bare module and relies on this fallback to hit the canonical
    main-repo DB.
    """

    def test_evaluate_without_yoke_db_env_falls_back(
        self, registry_db, monkeypatch
    ):
        monkeypatch.delenv("YOKE_DB", raising=False)
        fallback_called = {"hit": False}

        def fake_fallback() -> str:
            fallback_called["hit"] = True
            return registry_db

        monkeypatch.setattr(lint_mod, "_resolve_db_fallback", fake_fallback)
        decision = evaluate(_record(_payload('sh emit-event.sh --name "ActiveEvent"')))
        assert decision.outcome is Outcome.NOOP
        assert fallback_called["hit"] is True, (
            "evaluate() must consult the Python resolver when YOKE_DB is "
            "unset (YOK-1384)"
        )

    def test_evaluate_prefers_yoke_db_env_when_set(
        self, registry_db, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("YOKE_DB", registry_db)
        fallback_called = {"hit": False}

        def fake_fallback() -> str:
            fallback_called["hit"] = True
            return str(tmp_path / "should-not-be-used.db")

        monkeypatch.setattr(lint_mod, "_resolve_db_fallback", fake_fallback)
        decision = evaluate(_record(_payload("echo hello")))
        assert decision.outcome is Outcome.NOOP
        assert fallback_called["hit"] is False, (
            "evaluate() must not consult the Python resolver when "
            "YOKE_DB is already set"
        )

    def test_main_runs_evaluate_via_fallback_db(
        self, registry_db, monkeypatch, capsys
    ):
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setattr(
            lint_mod, "_resolve_db_fallback", lambda: registry_db
        )
        payload = _payload('sh emit-event.sh --name "ActiveEvent"')
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        rc = lint_mod.main()
        assert rc == 0
        captured = capsys.readouterr()
        # ActiveEvent in the registry → no deny, no stdout.
        assert captured.out == ""

    def test_resolve_db_fallback_degrades_silently(self, monkeypatch):
        def explode() -> str:
            raise RuntimeError("simulated resolver failure")

        monkeypatch.setattr(
            "yoke_core.domain.db_helpers.resolve_db_path", explode
        )
        assert lint_mod._resolve_db_fallback() == ""


class TestMain:
    def test_main_writes_deny_envelope_to_stdout(
        self, registry_db, monkeypatch, capsys
    ):
        monkeypatch.setenv("YOKE_DB", registry_db)
        payload = _payload('sh emit-event.sh --name "Unknown"')
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        with mock.patch(
            "runtime.harness.hook_runner.telemetry.emit_denial_event"
        ):
            rc = lint_mod.main()
        assert rc == 0
        captured = capsys.readouterr()
        assert '"permissionDecision": "deny"' in captured.out

    def test_main_invalid_payload_silent(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
        rc = lint_mod.main()
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
