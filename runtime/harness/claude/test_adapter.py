"""Smoke tests for the Claude adapter capability (AC-T1 .. AC-T5).

Full universal-ordering parity tests live in Task 014's
`runtime/harness/test_hook_runner.py`. This file covers only the per-task
acceptance criteria for Task 004: import works, family is correct,
`apply_patch_chain_omissions` is empty, the Claude events are present,
and the adapter file has zero `def` declarations.
"""

from __future__ import annotations

from pathlib import Path

from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.stdin import parse_json_payload


def test_capability_imports() -> None:
    # AC-T1: module-level CAPABILITY is importable.
    from runtime.harness.claude.adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_claude() -> None:
    # AC-T2.
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.family == "claude"


def test_apply_patch_chain_omissions_empty() -> None:
    # AC-T3: Claude includes lint_write_path; only Codex omits it.
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset()
    assert CAPABILITY.pretool_omissions == frozenset()
    assert CAPABILITY.subprocess_modules == frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    )


def test_events_cover_claude_matrix() -> None:
    # AC-T4: every event in the spec's Event Coverage Matrix for Claude.
    from runtime.harness.claude.adapter import CAPABILITY

    expected = frozenset(
        {
            "SessionStart",
            "SessionEnd",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "Notification",
            "SubagentStop",
            "PreCompact",
        }
    )
    assert CAPABILITY.events == expected


def test_callables_bound_by_reference_not_wrappers() -> None:
    # Reuse posture: the adapter binds existing callables directly.
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.payload_parser is parse_json_payload
    assert CAPABILITY.decision_renderer is render_claude_decision


def test_adapter_module_has_zero_def_declarations() -> None:
    # AC-T5: zero `def ` at column 0 in adapter.py — no policy logic.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], f"adapter.py must contain zero def declarations, found: {def_lines}"


def test_adapter_module_under_80_lines() -> None:
    # AC-T6: file under 80 lines.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 80, f"adapter.py is {line_count} lines, must be <=80"
