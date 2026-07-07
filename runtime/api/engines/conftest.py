"""Engines-test isolation fixtures.

By default, doctor health-check tests must not read the live machine
``~/.yoke/config.json``. Cutoff readers consult machine config on every HC
invocation; without this fixture, fast in-memory tests that seed low item ids
could be silently suppressed by live cutoff values and fail with unhelpful
PASS-when-WARN-expected assertions.

The fixture points ``yoke_core.engines.doctor_report._resolve_repo_root`` at
a per-session empty temp directory and points ``YOKE_MACHINE_CONFIG_FILE`` at
an empty per-session JSON config. Tests that DO want to exercise
repo-root-dependent paths or cutoff values layer their own ``patch(...)`` /
``patch.dict(...)`` context manager INSIDE the test, which takes precedence
over the outer autouse patch.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="session")
def _engines_isolated_repo_root():
    """Session-scoped empty directory served as the isolated repo root."""
    with tempfile.TemporaryDirectory(prefix="yoke-engines-isolated-") as tmp:
        root = Path(tmp)
        cfg = root / ".yoke" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{"settings": {}, "projects": {}}\n')
        yield str(root), str(cfg)


@pytest.fixture(autouse=True)
def _isolate_engines_from_live_config(_engines_isolated_repo_root):
    """Block engines tests from reading the live machine config by default.

    Per-test overrides via ``with patch(...)`` continue to win because
    ``unittest.mock.patch`` uses a stack.
    """
    repo_root, config_path = _engines_isolated_repo_root
    with patch(
        "yoke_core.engines.doctor_report._resolve_repo_root",
        return_value=repo_root,
    ), patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": config_path}):
        yield
