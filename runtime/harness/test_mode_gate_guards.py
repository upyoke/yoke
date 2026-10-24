"""Registered guards return a plain deny; only mode_gate applies warn mode."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.hook_guard_catalog import GUARD_CATALOG
from yoke_core.domain import lint_watcher_module_form as guard
from yoke_core.hooks import mode_gate
from yoke_core.hooks.guard_denial_record import record_guard_decision
from yoke_core.hooks.types import HookContext, Outcome

_DOMAIN = Path(importlib.util.find_spec("yoke_core.domain").origin).parent
_MODULE_ID = "yoke_core.domain.lint_watcher_module_form"


def _context(mode: str) -> HookContext:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "python3 -m yoke_core.tools.watch_pytest"},
        lint_policy.SNAPSHOT_PAYLOAD_KEY: {"lint_watcher_module_form": {"mode": mode}},
    }
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name="Bash",
        session_id="sess-test",
    )


def _record(mode: str, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[dict]]:
    rows: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.hooks.denial.emit_denial_event", lambda **kw: rows.append(kw),
    )
    context = _context(mode)
    decision = mode_gate.apply_mode(guard.evaluate(context), _MODULE_ID, context=context)
    record_guard_decision(decision, _MODULE_ID, context=context)
    return decision, rows


def test_warn_configured_guard_records_one_warn_row(monkeypatch):
    decision, rows = _record("warn", monkeypatch)
    assert decision.outcome is Outcome.WARN and not decision.block
    assert decision.message == ""
    assert [row["outcome"] for row in rows] == ["warn"]
    assert rows[0]["mode"] == "warn"
    assert rows[0]["reason"].startswith(
        "guard lint-watcher-module-form downgraded deny->warn by .yoke/lint-config"
    )


def test_deny_configured_guard_records_one_denied_row(monkeypatch):
    decision, rows = _record("deny", monkeypatch)
    assert decision.outcome is Outcome.DENY and decision.block
    assert "legacy watcher module form" in decision.message
    assert [row["outcome"] for row in rows] == ["denied"]
    assert rows[0]["mode"] == "deny"


def test_no_guard_source_records_warned():
    offenders = [
        path.name for path in sorted(_DOMAIN.glob("*.py"))
        if '"warned"' in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.parametrize("spec", GUARD_CATALOG, ids=lambda spec: spec.guard)
def test_registered_guard_reads_no_mode_and_no_tool_name_copy(spec):
    found = importlib.util.find_spec(".".join(spec.module.split(".")[:3]))
    source = Path(found.origin).read_text(encoding="utf-8")
    for needle in (
        "def _read_mode", "def _extract_tool_name", "def _tool_name", "resolve_mode_for_payload",
    ):
        assert needle not in source, f"{spec.module} defines {needle}"
