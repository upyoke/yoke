"""Where the local-verification default and this repo's full gate are taught.

Both used to be asserted against the bootstrap renders, which carried them
only because those renders inlined the whole packet and the whole repo-internal
rules section. The compact render feeds a hook reply with a 2,500-byte ceiling
on Codex, so it now names the packet instead of embedding it, and the
repo-internal source-dev doctrine lives in its own document. Each fact is
asserted where it is actually taught.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.hooks.bootstrap import load_spec, render_compact, render_full


IMPACTED_LOCAL_CHECK = "yoke watch pytest --impacted main --bounded"
# This repo's own test anchors. They are deliberately absent from every surface
# the install bundle ships to other projects — a target project's anchors are
# its own — so they stay in the repo-local source-dev doctrine.
FULL_YOKE_GATE = "yoke watch pytest -- runtime/api/ runtime/harness/ tests/"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _spec() -> dict:
    return load_spec(REPO_ROOT / "runtime/harness/bootstrap-spec.json")


def test_rules_file_teaches_the_local_verification_default() -> None:
    """A session gets this from the rules file it already loads."""
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert IMPACTED_LOCAL_CHECK in agents
    assert FULL_YOKE_GATE not in agents, (
        "this repo's own anchors belong in the source-dev doctrine, not in "
        "the rules file the install bundle ships"
    )


def test_source_dev_doctrine_teaches_this_repo_full_gate() -> None:
    doctrine = (REPO_ROOT / "docs/source-dev-doctrine.md").read_text(
        encoding="utf-8"
    )
    assert FULL_YOKE_GATE in doctrine
    assert IMPACTED_LOCAL_CHECK in doctrine
    assert "inject xdist `-n auto`" in doctrine


def test_rules_file_points_at_the_doctrine_that_carries_the_rest() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/source-dev-doctrine.md" in agents


def test_compact_bootstrap_stays_small_enough_to_deliver() -> None:
    """The compact render rides a hook reply; Codex caps that at 2,500 bytes."""
    from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness

    rendered = render_compact(REPO_ROOT, _spec())
    assert FULL_YOKE_GATE not in rendered
    assert len(rendered.encode("utf-8")) < inline_context_bytes_for_harness("codex")


def test_full_bootstrap_is_a_deliberate_read_and_names_the_packet() -> None:
    rendered = render_full(REPO_ROOT, _spec())
    assert "yoke packets render --role main_agent" in rendered
    assert "=== AGENTS.md ===" in rendered
