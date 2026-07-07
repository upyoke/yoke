"""Smoke tests for the Codex adapter capability (AC-T1 .. AC-T9).

Full universal-ordering parity tests live in Task 014's
`runtime/harness/test_hook_runner.py`. This file covers only the
per-task acceptance criteria for Task 005: import works, family is
correct, `apply_patch_chain_omissions` and `subprocess_modules` carry
the documented values, the events frozenset matches the spec's Event
Coverage Matrix Codex column, the adapter file has zero `def`
declarations, and the service-bridge / payload module surfaces the
adapter depends on still resolve.
"""

from __future__ import annotations

from pathlib import Path

from runtime.harness.codex.codex_hooks_payload import _parse_payload, normalize_tool_event
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_codex_decision


def test_capability_imports() -> None:
    # AC-T1: module-level CAPABILITY is importable.
    from runtime.harness.codex.adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_codex() -> None:
    # AC-T2.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.family == "codex"


def test_apply_patch_chain_omissions_match_spec() -> None:
    # AC-T3: Codex omits lint_write_path on the apply_patch chain.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset(
        {"yoke_core.domain.lint_write_path"}
    )
    assert CAPABILITY.pretool_omissions == frozenset()


def test_subprocess_modules_match_spec() -> None:
    # AC-T4: observe + db_error_hook dispatch via subprocess.run per GAP #2.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.subprocess_modules == frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    )


def test_events_cover_codex_matrix() -> None:
    # AC-T5: every event in the spec's Event Coverage Matrix Codex column.
    from runtime.harness.codex.adapter import CAPABILITY

    expected = frozenset(
        {
            "SessionStart",
            "SessionEnd",
            "Stop",
            "UserPromptSubmit",
            "apply_patch",
        }
    )
    assert CAPABILITY.events == expected


def test_callables_bound_by_reference_not_wrappers() -> None:
    # Reuse posture: the adapter binds existing callables directly.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.payload_parser is _parse_payload
    assert CAPABILITY.decision_renderer is render_codex_decision


def test_adapter_module_has_zero_def_declarations() -> None:
    # AC-T6: zero `def ` at column 0 in adapter.py — no policy logic.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], f"adapter.py must contain zero def declarations, found: {def_lines}"


def test_payload_module_line_budget() -> None:
    # AC-T8: codex_hooks_payload.py line count is <=329.
    payload_path = (
        Path(__file__).resolve().parent / "codex_hooks_payload.py"
    )
    line_count = len(payload_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 329, (
        f"codex_hooks_payload.py is {line_count} lines, must be <=329"
    )


def test_normalize_tool_event_still_importable() -> None:
    # AC-T9 [READ-ONLY]: normalize_tool_event remains exported per File Budget.
    assert callable(normalize_tool_event)


def test_adapter_module_under_140_lines() -> None:
    # Per-task per-file budget: <=140 lines.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 140, f"adapter.py is {line_count} lines, must be <=140"
