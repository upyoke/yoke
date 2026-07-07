"""Codex `AdapterCapability` instance consumed by the shared hook runner.

The adapter is data-only: it names the events Codex subscribes to, points at
the existing JSON payload parser (`_parse_payload`) and the Codex-shaped
decision renderer, declares the `apply_patch` chain omission for
`lint_write_path` (Codex routes write-class tool calls through `apply_patch`
and the write-path lint is intentionally skipped on that chain), and lists
the two policy modules that dispatch via `subprocess.run` instead of the
runner's typed `importlib + evaluate(record)` path.

The `payload_parser` binds `_parse_payload` directly — its signature
(``(payload: str) -> dict``) matches the runner's call shape.

The runner's `__main__` lazily imports this module for the detected
harness; no policy-evaluation code lives here.
"""

from __future__ import annotations

from runtime.harness.codex.codex_hooks_payload import _parse_payload
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import render_codex_decision

__all__ = ["CAPABILITY"]


CAPABILITY: AdapterCapability = AdapterCapability(
    family="codex",
    events=frozenset(
        {
            "SessionStart",
            "SessionEnd",
            "Stop",
            "UserPromptSubmit",
            "apply_patch",
        }
    ),
    payload_parser=_parse_payload,
    decision_renderer=render_codex_decision,
    apply_patch_chain_omissions=frozenset({"yoke_core.domain.lint_write_path"}),
    pretool_omissions=frozenset(),
    subprocess_modules=frozenset(
        {
            "yoke_core.domain.observe",
            "yoke_core.domain.db_error_hook",
        }
    ),
)
