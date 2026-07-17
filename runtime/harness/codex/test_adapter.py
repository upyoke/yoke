"""Smoke tests for the Codex adapter capability.

Full universal-ordering parity tests live in
`runtime/harness/test_hook_runner_parity.py`. This file covers only the
adapter's own contract: import works, family is correct, no chain
omissions are declared, `subprocess_modules` carries the documented
carve-outs, the adapter file stays data-only, and the payload module
surfaces the adapter depends on still resolve.
"""

from __future__ import annotations

from pathlib import Path

from runtime.harness.codex.codex_hooks_payload import _parse_payload, normalize_tool_event
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_codex_decision


def test_capability_imports() -> None:
    # Module-level CAPABILITY is importable.
    from runtime.harness.codex.adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_codex() -> None:
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.family == "codex"


def test_no_chain_omissions_declared() -> None:
    # Codex runs the same universal chains as Claude; the apply_patch
    # chain intentionally shares the Edit/Write gate ordering.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset()
    assert CAPABILITY.pretool_omissions == frozenset()


def test_subprocess_modules_carveout() -> None:
    # observe + db_error_hook dispatch via subprocess.run instead of the
    # runner's typed importlib + evaluate(record) path.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.subprocess_modules == frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    )


def test_callables_bound_by_reference_not_wrappers() -> None:
    # Reuse posture: the adapter binds existing callables directly.
    from runtime.harness.codex.adapter import CAPABILITY

    assert CAPABILITY.payload_parser is _parse_payload
    assert CAPABILITY.decision_renderer is render_codex_decision


def test_adapter_module_has_zero_def_declarations() -> None:
    # Data-only contract: zero `def ` at column 0 in adapter.py — no policy logic.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], f"adapter.py must contain zero def declarations, found: {def_lines}"


def test_payload_module_line_budget() -> None:
    # codex_hooks_payload.py stays within its line budget.
    payload_path = (
        Path(__file__).resolve().parent / "codex_hooks_payload.py"
    )
    line_count = len(payload_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 329, (
        f"codex_hooks_payload.py is {line_count} lines, must be <=329"
    )


def test_normalize_tool_event_still_importable() -> None:
    # normalize_tool_event remains an exported surface for payload consumers.
    assert callable(normalize_tool_event)


def test_adapter_module_under_140_lines() -> None:
    # Data-only adapters stay small: 140-line budget.
    adapter_path = Path(__file__).resolve().parent / "adapter.py"
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 140, f"adapter.py is {line_count} lines, must be <=140"
