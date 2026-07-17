"""Smoke tests for the Claude adapter capability.

Full universal-ordering parity tests live in
`runtime/harness/test_hook_runner_parity.py`. This file covers only the
adapter's own contract: import works, family is correct, no chain
omissions are declared, callables bind by reference, and the adapter
file stays data-only.
"""

from __future__ import annotations

from pathlib import Path

from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_claude_decision
from runtime.harness.hook_runner.stdin import parse_json_payload


def test_capability_imports() -> None:
    # Module-level CAPABILITY is importable.
    from runtime.harness.claude.adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_claude() -> None:
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.family == "claude"


def test_no_chain_omissions_declared() -> None:
    # Claude runs every universal chain unfiltered.
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset()
    assert CAPABILITY.pretool_omissions == frozenset()
    assert CAPABILITY.subprocess_modules == frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    )


def test_callables_bound_by_reference_not_wrappers() -> None:
    # Reuse posture: the adapter binds existing callables directly.
    from runtime.harness.claude.adapter import CAPABILITY

    assert CAPABILITY.payload_parser is parse_json_payload
    assert CAPABILITY.decision_renderer is render_claude_decision


def test_adapter_module_has_zero_def_declarations() -> None:
    # Data-only contract: zero `def ` at column 0 in adapter.py — no policy logic.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], f"adapter.py must contain zero def declarations, found: {def_lines}"


def test_adapter_module_under_80_lines() -> None:
    # Data-only adapters stay small: 80-line budget.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 80, f"adapter.py is {line_count} lines, must be <=80"
