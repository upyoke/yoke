"""Smoke tests for the Codex adapter capability.

Full universal-ordering parity tests live in
`runtime/harness/test_hook_runner_parity.py`. This file covers only the
adapter's own contract: import works, family is correct, no chain
omissions are declared, `subprocess_modules` is empty (typed evaluate),
the adapter file stays data-only, and the payload module
surfaces the adapter depends on still resolve.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.hooks import codex_adapter, codex_payload
from yoke_core.hooks.codex_payload import _parse_payload, normalize_tool_event
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_codex_decision


def test_capability_imports() -> None:
    # Module-level CAPABILITY is importable.
    from yoke_core.hooks.codex_adapter import CAPABILITY

    assert isinstance(CAPABILITY, AdapterCapability)


def test_capability_family_is_codex() -> None:
    from yoke_core.hooks.codex_adapter import CAPABILITY

    assert CAPABILITY.family == "codex"


def test_no_chain_omissions_declared() -> None:
    # Codex runs the same universal chains as Claude; the apply_patch
    # chain intentionally shares the Edit/Write gate ordering.
    from yoke_core.hooks.codex_adapter import CAPABILITY

    assert CAPABILITY.apply_patch_chain_omissions == frozenset()
    assert CAPABILITY.pretool_omissions == frozenset()


def test_subprocess_modules_carveout() -> None:
    from yoke_core.hooks.codex_adapter import CAPABILITY

    assert CAPABILITY.subprocess_modules == frozenset()


def test_callables_bound_by_reference_not_wrappers() -> None:
    # Reuse posture: the adapter binds existing callables directly.
    from yoke_core.hooks.codex_adapter import CAPABILITY

    assert CAPABILITY.payload_parser is _parse_payload
    assert CAPABILITY.decision_renderer is render_codex_decision


def test_adapter_module_has_zero_def_declarations() -> None:
    # Data-only contract: zero `def ` at column 0 in adapter.py — no policy logic.
    adapter_path = Path(codex_adapter.__file__).resolve()
    source = adapter_path.read_text(encoding="utf-8")
    def_lines = [line for line in source.splitlines() if line.startswith("def ")]
    assert def_lines == [], (
        f"adapter.py must contain zero def declarations, found: {def_lines}"
    )


def test_payload_module_line_budget() -> None:
    # codex_payload.py stays within its line budget.
    payload_path = Path(codex_payload.__file__).resolve()
    line_count = len(payload_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 329, f"codex_payload.py is {line_count} lines, must be <=329"


def test_normalize_tool_event_still_importable() -> None:
    # normalize_tool_event remains an exported surface for payload consumers.
    assert callable(normalize_tool_event)


def test_adapter_module_under_140_lines() -> None:
    # Data-only adapters stay small: 140-line budget.
    adapter_path = Path(codex_adapter.__file__).resolve()
    line_count = len(adapter_path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 140, f"adapter.py is {line_count} lines, must be <=140"
