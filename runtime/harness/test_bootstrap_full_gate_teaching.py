"""Bootstrap teaching for local verification and this repo's full gate."""

from __future__ import annotations

from pathlib import Path

from yoke_core.hooks.bootstrap import load_spec, render_compact, render_full


IMPACTED_LOCAL_CHECK = "yoke watch pytest --impacted main --bounded"
# This repo's own test anchors. They are deliberately absent from every
# surface the install bundle ships to other projects — a target project's
# anchors are its own — so they reach the bootstrap only through AGENTS.md,
# which stays repo-local below the managed-block marker. The compact
# render carries the shipped packet rather than that section, so it teaches
# the project-neutral default and nothing repo-specific.
FULL_YOKE_GATE = (
    "yoke watch pytest -- runtime/api/ runtime/harness/ tests/"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _spec() -> dict:
    return load_spec(REPO_ROOT / "runtime/harness/bootstrap-spec.json")


def test_compact_bootstrap_teaches_the_project_neutral_local_default() -> None:
    rendered = render_compact(REPO_ROOT, _spec())
    assert IMPACTED_LOCAL_CHECK in rendered
    assert "inject xdist `-n auto`" in rendered
    assert FULL_YOKE_GATE not in rendered


def test_full_bootstrap_teaches_this_repo_full_gate() -> None:
    rendered = render_full(REPO_ROOT, _spec())
    assert IMPACTED_LOCAL_CHECK in rendered
    assert FULL_YOKE_GATE in rendered
    assert "inject xdist `-n auto`" in rendered
