"""Delivery bounds for the bootstrap renders.

The compact render feeds a hook reply with a 2,500-byte ceiling on Codex, so it
names the packet instead of embedding it. The full render is a deliberate read
that still carries the rules file.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.hooks.bootstrap import load_spec, render_compact, render_full


REPO_ROOT = Path(__file__).resolve().parents[2]


def _spec() -> dict:
    return load_spec(REPO_ROOT / "runtime/harness/bootstrap-spec.json")


def test_compact_bootstrap_stays_small_enough_to_deliver() -> None:
    """The compact render rides a hook reply; Codex caps that at 2,500 bytes."""
    from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness

    rendered = render_compact(REPO_ROOT, _spec())
    assert len(rendered.encode("utf-8")) < inline_context_bytes_for_harness("codex")


def test_full_bootstrap_includes_the_rules_file() -> None:
    rendered = render_full(REPO_ROOT, _spec())
    assert "=== AGENTS.md ===" in rendered
