"""Shared workspace-anchored helper for renderer test modules.

Replaces the previous per-test ``repo_root`` fixture pattern that called
``agents_render._repo_root()`` directly. The old pattern resolved the
checkout root through ``git rev-parse --show-toplevel`` at the test
subprocess's cwd, which made byte-identity assertions sensitive to the
process cwd: re-running pytest from main, from a linked worktree, or from
``/tmp`` could silently target three different checkouts and turn a
cwd-resolution failure into something that looked like a real
render-vs-disk drift.

This module owns one canonical helper, :func:`resolve_live_repo_root`,
that resolves the checkout root from one of two explicit anchors:

1. ``$YOKE_BOUND_WORKSPACE`` when set (the SessionStart-exported anchor).
2. ``Path(__file__)`` walk-up to the directory containing ``runtime/agents``.

The helper never consults the process cwd. Test files import the helper
and declare their own thin ``repo_root`` fixture so the resolution stays
explicit at the test site — the cross-cwd regression test asserts
that the three byte-identity tests produce identical outcomes under three
distinct cwd values precisely because the fixture is workspace-anchored.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.domain.agents_render_workspace import BOUND_WORKSPACE_ENV_VAR


def resolve_live_repo_root() -> Path:
    """Return the live Yoke checkout root without touching the cwd.

    Prefers ``$YOKE_BOUND_WORKSPACE`` when set so test reads target the
    same checkout the agent session is bound to; otherwise walks up from
    this module's ``__file__`` to the directory that contains
    ``runtime/agents``. Raises ``RuntimeError`` when neither anchor is
    usable (a structurally impossible state inside a Yoke checkout, but
    surfaced explicitly so a future packaging refactor does not silently
    fall back to ``git rev-parse``).
    """
    workspace = os.environ.get(BOUND_WORKSPACE_ENV_VAR, "").strip()
    if workspace:
        return Path(workspace).resolve()
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / "runtime" / "agents").is_dir():
            return p
        p = p.parent
    raise RuntimeError(
        "renderer test fixture: cannot resolve the live Yoke checkout "
        "root; neither $YOKE_BOUND_WORKSPACE nor the runtime/agents "
        "walk-up anchor produced a hit"
    )
