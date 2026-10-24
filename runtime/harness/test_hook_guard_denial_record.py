"""The hook runner records each guard denial exactly once, for every guard.

Guards never emit ``HarnessToolCallDenied``; the runner hands every decision
to :func:`yoke_core.hooks.guard_denial_record.record_guard_decision`. These
tests drive :func:`yoke_core.hooks.runner.run_event` and count the rows that
reach :func:`yoke_core.hooks.denial.emit_denial_event`.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from runtime.harness.test_hook_project_scope import project_map as project_map
from runtime.harness.test_hook_runner import _patch_typed_modules, _silence_telemetry
from yoke_core.hooks import denial
from yoke_core.hooks import runner as runner_module
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.claude_adapter import CAPABILITY as CLAUDE_CAPABILITY
from yoke_core.hooks.guard_denial_record import guard_audit_outcome
from yoke_core.hooks.types import HookDecision, Next, Outcome


STDERR_GUARD = "yoke_core.domain.lint_yoke_adapter_stderr_visibility"
HIDDEN_STDERR = "yoke lifecycle transition YOK-1 --to done 2>&1 | tail -5"


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(denial, "emit_denial_event", lambda **kw: rows.append(kw))
    _silence_telemetry(monkeypatch)
    return rows


def _run(
    command: str,
    tmp_path,
    project_map,
    monkeypatch: pytest.MonkeyPatch,
    *,
    chain: list[str] | None = None,
) -> tuple[str, int]:
    project_map["connection_projects"]["local"] = [
        {"checkout": str(tmp_path), "project_id": 1}
    ]
    if chain is not None:
        monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-denial-record",
        "tool_use_id": "toolu-1",
        "cwd": str(tmp_path),
    }
    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: payload,
        decision_renderer=CLAUDE_CAPABILITY.decision_renderer,
        subprocess_modules=CLAUDE_CAPABILITY.subprocess_modules,
        apply_patch_chain_omissions=CLAUDE_CAPABILITY.apply_patch_chain_omissions,
        pretool_omissions=CLAUDE_CAPABILITY.pretool_omissions,
    )
    return runner_module.run_event("PreToolUse", capability=capability, stdin_data="{}")


def test_denial_through_the_full_chain_is_recorded_once(
    recorded, tmp_path, project_map, monkeypatch
) -> None:
    _, exit_code = _run(HIDDEN_STDERR, tmp_path, project_map, monkeypatch)

    assert exit_code == 2
    assert len(recorded) == 1
    row = recorded[0]
    assert row["hook"] == STDERR_GUARD
    assert row["check_id"] == "lint-yoke-adapter-stderr-visibility"
    assert row["outcome"] == "denied"
    assert row["tool"] == "Bash"
    assert row["session_id"] == "sess-denial-record"
    assert row["tool_use_id"] == "toolu-1"
    assert row["command_snippet"] == HIDDEN_STDERR
    assert "Yoke check id: lint-yoke-adapter-stderr-visibility" in row["reason"]


SILENT_GUARD = "tests.silent_guard"


def _install_silent_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guard that always blocks and never emits anything itself."""

    def evaluate(_context):
        return HookDecision(
            outcome=Outcome.DENY,
            message="refused by a guard with no emitter",
            audit_fields={"reason": "refused by a guard with no emitter"},
            block=True,
            next=Next.STOP,
        )

    _patch_typed_modules(
        monkeypatch, {SILENT_GUARD: types.SimpleNamespace(evaluate=evaluate)}
    )


def test_guard_that_never_emitted_is_recorded_once(
    recorded, tmp_path, project_map, monkeypatch
) -> None:
    module_id = SILENT_GUARD
    _install_silent_guard(monkeypatch)
    _, exit_code = _run("echo hi", tmp_path, project_map, monkeypatch, chain=[module_id])

    assert exit_code == 2
    assert [(r["hook"], r["check_id"], r["outcome"]) for r in recorded] == [
        (module_id, "silent_guard", "denied")
    ]
    assert recorded[0]["reason"] == "refused by a guard with no emitter"


def test_allowed_call_records_nothing(
    recorded, tmp_path, project_map, monkeypatch
) -> None:
    _, exit_code = _run("echo hello", tmp_path, project_map, monkeypatch)

    assert exit_code == 0
    assert recorded == []


def test_warn_mode_downgrade_is_recorded_once_as_warn(
    recorded, tmp_path, project_map, monkeypatch
) -> None:
    from yoke_core.hooks import mode_gate

    monkeypatch.setattr(mode_gate.lint_config, "is_registered", lambda m: True)
    monkeypatch.setattr(mode_gate.lint_config, "resolve_mode", lambda m, **k: "warn")
    monkeypatch.setattr(
        mode_gate.lint_config, "resolve_mode_from_snapshot", lambda m, s: "warn"
    )
    _install_silent_guard(monkeypatch)
    _, exit_code = _run("echo hi", tmp_path, project_map, monkeypatch, chain=[SILENT_GUARD])

    assert exit_code == 0
    assert [(r["hook"], r["outcome"]) for r in recorded] == [(SILENT_GUARD, "warn")]
    assert "downgraded deny->warn" in recorded[0]["reason"]


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (HookDecision(outcome=Outcome.DENY, block=True), "denied"),
        (
            HookDecision(
                outcome=Outcome.DENY,
                block=True,
                audit_fields={"audit_outcome": "suppression_attempted"},
            ),
            "suppression_attempted",
        ),
        (HookDecision(outcome=Outcome.WARN, audit_fields={"audit_outcome": "denied"}), "warn"),
        (
            HookDecision(
                outcome=Outcome.AUDIT_ONLY,
                audit_fields={"audit_outcome": "suppression_attempted"},
            ),
            "suppression_attempted",
        ),
        (HookDecision(outcome=Outcome.WARN, message="advisory"), ""),
        (HookDecision(outcome=Outcome.NOOP), ""),
    ],
)
def test_guard_audit_outcome(decision: HookDecision, expected: str) -> None:
    assert guard_audit_outcome(decision) == expected
