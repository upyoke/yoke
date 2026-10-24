"""lint_event_registry — evaluate / main canonical-fallback coverage.

Split out of ``test_lint_event_registry.py`` to keep authored files under the
350-line limit.
"""

# ruff: noqa: F811

from __future__ import annotations

import io
import json

from yoke_core.domain import lint_event_registry as lint_mod
from yoke_core.domain.lint_event_registry import evaluate
from runtime.api.domain.lint_event_registry_test_helpers import (  # noqa: F401 — fixtures
    _payload,
    registry_db,
)
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
from yoke_core.hooks.types import Next, Outcome


def _record(payload_json: str):
    """Build a HookContext from a serialized payload as evaluate() expects."""
    data = json.loads(payload_json)
    return lint_mod._build_context_from_payload(data)


class TestEvaluate:
    def test_allow_returns_noop_no_streams(self, registry_db, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", registry_db)
        decision = evaluate(
            _record(_payload('sh emit-event.sh --name "RegisteredEvent"'))
        )
        assert decision.outcome is Outcome.NOOP
        assert decision.next is Next.CONTINUE
        assert decision.message == ""
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_deny_carries_envelope_and_audit_reason(self, registry_db, monkeypatch):
        monkeypatch.setenv("YOKE_DB", registry_db)
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
        assert decision.audit_fields["event_name"] == "Unknown"
        assert "Unknown" in decision.audit_fields["reason"]
        assert guard_audit_outcome(decision) == "denied"

    def test_empty_payload_returns_noop(self, registry_db, monkeypatch):
        monkeypatch.setenv("YOKE_DB", registry_db)
        ctx = lint_mod._build_context_from_payload({})
        decision = evaluate(ctx)
        assert decision.outcome is Outcome.NOOP


class TestYok1384CanonicalFallback:
    """``lint_event_registry.main()`` and :func:`evaluate` must stay
    fail-open when no file-DB token is available.

    Prior to the tracked-launcher fix the Claude PreToolUse launcher injected
    the worktree-local DB path directly, silently bypassing the Python
    worktree-aware resolver from inside linked worktrees. The launcher now
    runs the bare module and relies on this fallback to hit the canonical
    main-repo DB.
    """

    def test_evaluate_without_yoke_db_env_falls_back(self, registry_db, monkeypatch):
        monkeypatch.delenv("YOKE_DB", raising=False)
        fallback_called = {"hit": False}

        def fake_fallback() -> str:
            fallback_called["hit"] = True
            return registry_db

        monkeypatch.setattr(lint_mod, "_resolve_db_fallback", fake_fallback)
        decision = evaluate(
            _record(_payload('sh emit-event.sh --name "RegisteredEvent"'))
        )
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

    def test_main_runs_evaluate_via_fallback_db(self, registry_db, monkeypatch, capsys):
        monkeypatch.delenv("YOKE_DB", raising=False)
        monkeypatch.setattr(lint_mod, "_resolve_db_fallback", lambda: registry_db)
        payload = _payload('sh emit-event.sh --name "RegisteredEvent"')
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        rc = lint_mod.main()
        assert rc == 0
        captured = capsys.readouterr()
        # RegisteredEvent in the registry → no deny, no stdout.
        assert captured.out == ""

    def test_resolve_db_fallback_degrades_silently(self, monkeypatch):
        assert lint_mod._resolve_db_fallback() == ""


class TestMain:
    def test_main_writes_deny_envelope_to_stdout(
        self, registry_db, monkeypatch, capsys
    ):
        monkeypatch.setenv("YOKE_DB", registry_db)
        payload = _payload('sh emit-event.sh --name "Unknown"')
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
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
