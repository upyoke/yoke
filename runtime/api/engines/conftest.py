"""Engines-test isolation fixtures.

By default, doctor health-check tests must not read the live machine
``~/.yoke/config.json``. Cutoff readers consult machine config on every HC
invocation; without this fixture, fast in-memory tests that seed low item ids
could be silently suppressed by live cutoff values and fail with unhelpful
PASS-when-WARN-expected assertions.

The fixture points ``yoke_core.engines.doctor_report._resolve_repo_root`` at
a per-session empty temp directory and points ``YOKE_MACHINE_CONFIG_FILE`` at
an empty per-session JSON config. Tests that DO want to exercise
repo-root-dependent paths or cutoff values layer their own ``patch(...)``,
``patch.dict(...)`` or ``monkeypatch`` override INSIDE the test, which takes
precedence over the autouse isolation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from runtime.api.engines._merge_landed_lane_test_helpers import (
    build_landed_lane,
)


@pytest.fixture(scope="session")
def _engines_isolated_repo_root():
    """Session-scoped empty directory served as the isolated repo root."""
    with tempfile.TemporaryDirectory(prefix="yoke-engines-isolated-") as tmp:
        root = Path(tmp)
        cfg = root / ".yoke" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{"settings": {}, "projects": []}\n')
        yield str(root), str(cfg)


@pytest.fixture(autouse=True)
def _isolate_engines_from_live_config(_engines_isolated_repo_root, monkeypatch):
    """Block engines tests from reading the live machine config by default.

    The isolation shares ``monkeypatch``'s undo stack with the test's own
    ``monkeypatch.setenv`` calls, so teardown unwinds them in reverse order and
    no test's temporary environment survives into the next test. ``HOME`` is
    the repo-wide per-test home from ``runtime.real_home_isolation``. Per-test
    overrides via ``with patch(...)`` or ``monkeypatch`` still win.
    """
    repo_root, config_path = _engines_isolated_repo_root
    monkeypatch.setattr(
        "yoke_core.engines.doctor_report._resolve_repo_root",
        lambda *_args, **_kwargs: repo_root,
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", config_path)
    monkeypatch.setenv("YOKE_MACHINE_HOME", "")


@pytest.fixture()
def landed_lane(tmp_path: Path):
    """A repo whose lane branch is merged and pushed, with a live worktree.

    Shared by the landed-lane retirement tests and the declared-residue pair,
    so both exercise the same real repository shape.
    """
    return build_landed_lane(tmp_path)
