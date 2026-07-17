"""Tests for ``runtime.harness.hook_runner.telemetry``.

After the cutover the legacy ``session_hooks_*`` per-event
sibling modules are deleted; telemetry re-exports now resolve to the
new ``hook_runner.{denial,identity,service_client,stdin}`` siblings.

Same-object semantics matter: callers do
``mock.patch("runtime.harness.hook_runner.telemetry.X", ...)`` and
expect the patch to take effect at every call site that imports
through the shim. A wrapper function (rather than a module-level
alias) would break that contract; this suite locks the alias shape
in place so the contract survives future re-organizations.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

import runtime.harness.hook_runner.denial as denial
import runtime.harness.hook_runner.identity as identity
import runtime.harness.hook_runner.service_client as svc_client
import runtime.harness.hook_runner.stdin as stdin
import runtime.harness.hook_runner.telemetry as telemetry
from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


# Names that are CALLABLES on the public surface. Each one is checked
# for callable-ness AND for same-object identity against its authoritative
# owner sibling.
_CALLABLE_RE_EXPORTS: tuple[str, ...] = (
    "_classify_session_id_source",
    "bounded_stdin_read",
    "build_denial_context",
    "build_denial_payload",
    "emit_denial_event",
    "emit_harness_session_sent_first_user_prompt_submit",
    "emit_session_hook_failed",
    "persist_session_id_to_env_file",
    "refresh_session_model_if_placeholder",
    "register_session",
    "resolve_direct_session_id",
    "resolve_env_init_session_id",
    "resolve_repo_root",
    "resolve_session_id_from_env_and_payload",
    "session_service_client_path",
)

# Module-level constants the shim re-exports.
_CONSTANT_RE_EXPORTS: tuple[str, ...] = (
    "COMMAND_SNIPPET_MAX_BYTES",
    "STDIN_FALLBACK_MAX_BYTES",
    "STDIN_FALLBACK_TIMEOUT_SECONDS",
)

# Map every public name on telemetry to its authoritative owner module.
_OWNER_FOR: dict[str, object] = {
    "COMMAND_SNIPPET_MAX_BYTES": denial,
    "build_denial_context": denial,
    "build_denial_payload": denial,
    "emit_denial_event": denial,
    "_classify_session_id_source": identity,
    "persist_session_id_to_env_file": identity,
    "resolve_direct_session_id": identity,
    "resolve_env_init_session_id": identity,
    "resolve_session_id_from_env_and_payload": identity,
    "refresh_session_model_if_placeholder": svc_client,
    "register_session": svc_client,
    "resolve_repo_root": svc_client,
    "session_service_client_path": svc_client,
    "STDIN_FALLBACK_MAX_BYTES": stdin,
    "STDIN_FALLBACK_TIMEOUT_SECONDS": stdin,
    "bounded_stdin_read": stdin,
    "emit_harness_session_sent_first_user_prompt_submit": stdin,
    "emit_session_hook_failed": stdin,
}


def test_every_callable_re_export_is_callable_on_telemetry() -> None:
    """Every legacy callable name resolves on telemetry and is callable."""
    for name in _CALLABLE_RE_EXPORTS:
        attr = getattr(telemetry, name)
        assert callable(attr), f"telemetry.{name} is not callable"


def test_every_callable_re_export_is_same_object_as_owner() -> None:
    """Each callable resolves to the same function object as its owner."""
    for name in _CALLABLE_RE_EXPORTS:
        owner = _OWNER_FOR[name]
        new = getattr(telemetry, name)
        legacy = getattr(owner, name)
        assert new is legacy, (
            f"telemetry.{name} is not the same object as {owner.__name__}.{name}"
        )


def test_constants_round_trip_through_telemetry() -> None:
    """Module-level constants survive the re-export verbatim."""
    for name in _CONSTANT_RE_EXPORTS:
        owner = _OWNER_FOR[name]
        assert hasattr(telemetry, name), f"telemetry.{name} is missing"
        assert getattr(telemetry, name) == getattr(owner, name)


def test_runner_native_emitters_present() -> None:
    """The three runner-native emitters live on telemetry, not the siblings."""
    for name in (
        "emit_hook_guardrail_evaluated",
        "emit_hook_execution_failed",
        "emit_hook_dispatch_telemetry",
    ):
        attr = getattr(telemetry, name)
        assert callable(attr), f"telemetry.{name} is not callable"


def test_runner_dispatch_populates_top_level_tool_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hook payload ``tool_name`` reaches the top-level ``events.tool_name`` column.

    Drives ``runner.run_event`` with a single typed allow-policy and a payload
    carrying ``tool_name="Bash"``. Captures the ``emit_event`` call telemetry makes
    for ``HookGuardrailEvaluated`` and asserts the top-level ``tool_name`` kwarg
    is populated — not just the nested ``context`` envelope.
    """

    def _allow(context: HookContext) -> HookDecision:  # noqa: ARG001
        return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    class _Mod:
        evaluate = staticmethod(_allow)

    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        return _Mod if name == "mod.allow" else real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.allow"])

    captured: list[dict[str, Any]] = []

    def fake_emit(event_name: str, **kwargs: Any):  # noqa: ARG001
        captured.append({"event_name": event_name, **kwargs})

    monkeypatch.setattr("yoke_core.domain.events.emit_event", fake_emit)

    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        decision_renderer=render_claude_decision,
    )

    runner_module.run_event("PreToolUse", capability=capability, stdin_data="{}")

    guardrail_rows = [c for c in captured if c["event_name"] == "HookGuardrailEvaluated"]
    assert guardrail_rows, "HookGuardrailEvaluated was not emitted"
    assert guardrail_rows[0]["tool_name"] == "Bash"


def test_flush_skips_throwaway_rows_and_resolves_floor_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The batched flush drops sub-floor rows before any write and resolves
    each event's severity floor once — not once per row.

    Injects a non-None connection and a fake floor check so the skip path is
    exercised deterministically (the bare unit env otherwise has no connection
    and the filter degrades to "emit everything").
    """
    from contextlib import contextmanager

    @contextmanager
    def fake_conn():
        yield object()  # sentinel: a non-None connection enables the filter

    floor_calls: list[str] = []

    def fake_check(conn: object, event_name: str, source_type: str, sev: str) -> bool:  # noqa: ARG001
        floor_calls.append(event_name)
        return event_name != "HookGuardrailEvaluated"  # DEBUG guardrail = throwaway

    monkeypatch.setattr(
        "yoke_core.domain.events_writes.hook_emit_connection", fake_conn,
    )
    monkeypatch.setattr(
        "yoke_core.domain.events_writes.check_severity_conn", fake_check,
    )

    guard: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    dispatch: list[dict[str, Any]] = []
    monkeypatch.setattr(telemetry, "emit_hook_guardrail_evaluated", lambda **k: guard.append(k))
    monkeypatch.setattr(telemetry, "emit_hook_execution_failed", lambda **k: failed.append(k))
    monkeypatch.setattr(telemetry, "emit_hook_dispatch_telemetry", lambda **k: dispatch.append(k))

    common = {
        "module": "m", "hook_event": "PreToolUse", "executor": "claude",
        "session_id": "s", "item_id": None, "tool_name": "Bash", "duration_ms": 1,
    }
    records = [
        ("guardrail", {**common, "decision_outcome": "noop"}),
        ("guardrail", {**common, "module": "m2", "decision_outcome": "noop"}),
        ("failed", {**common, "failure": "timeout_1ms"}),
        ("dispatch", {
            "hook_event": "PreToolUse", "executor": "claude", "chain_length": 3,
            "decision_outcome": "allow", "session_id": "s", "item_id": None,
            "tool_name": "Bash", "duration_ms": 5,
        }),
    ]
    telemetry.flush_hook_telemetry(records)

    assert guard == [], "sub-floor guardrail rows must be skipped before any write"
    assert len(failed) == 1, "WARN failure rows are keepers"
    assert len(dispatch) == 1, "INFO dispatch rows are keepers"
    # Resolve-once: the floor for the two guardrail rows is probed a single time.
    assert floor_calls.count("HookGuardrailEvaluated") == 1
