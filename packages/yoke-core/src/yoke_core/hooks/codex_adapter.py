"""Codex `AdapterCapability` instance consumed by the shared hook runner.

The adapter is data-only: it points at the existing JSON payload parser
(`_parse_payload`) and the Codex-shaped decision renderer, and declares
no chain omissions — Codex runs the same universal chains as Claude,
including the `apply_patch` chain, which shares the `Edit`/`Write` gate
ordering. Every chained policy is typed ``evaluate``; the runner's
``subprocess_modules`` carve-out stays empty.

The `payload_parser` binds `_parse_payload` directly — its signature
(``(payload: str) -> dict``) matches the runner's call shape.

The runner's `__main__` lazily imports this module for the detected
harness; no policy-evaluation code lives here.
"""

from __future__ import annotations

from yoke_core.hooks.codex_payload import _parse_payload
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.decision_render import render_codex_decision

__all__ = ["CAPABILITY"]


CAPABILITY: AdapterCapability = AdapterCapability(
    family="codex",
    payload_parser=_parse_payload,
    decision_renderer=render_codex_decision,
    apply_patch_chain_omissions=frozenset(),
    pretool_omissions=frozenset(),
)
