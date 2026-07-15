"""Bootstrap teaching for the canonical full Yoke verification gate."""

from __future__ import annotations

from pathlib import Path

from runtime.harness.bootstrap import load_spec, render_compact, render_full


FULL_YOKE_GATE = (
    "python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _spec() -> dict:
    return load_spec(REPO_ROOT / "runtime/harness/bootstrap-spec.json")


def test_compact_bootstrap_teaches_exact_full_yoke_gate() -> None:
    rendered = render_compact(REPO_ROOT, _spec())
    assert FULL_YOKE_GATE in rendered
    assert "it injects xdist `-n auto`" in rendered


def test_full_bootstrap_teaches_exact_full_yoke_gate() -> None:
    rendered = render_full(REPO_ROOT, _spec())
    assert FULL_YOKE_GATE in rendered
    assert "it injects xdist `-n auto`" in rendered
