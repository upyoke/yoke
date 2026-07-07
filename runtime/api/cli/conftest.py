"""Shared fixtures for Yoke CLI adapter tests.

Adapters are DB-free pre-dispatch under the relay contract: raw item
refs ride the envelope target (``TargetRef.item_ref``) and resolve
server-side in the dispatcher. CLI tests stub ``dispatch`` and assert
the captured envelope, so no item-ref parser stub is needed here.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_onboard_rich_glyphs(monkeypatch):
    """Keep wizard rendering tests independent of the runner's ambient TERM."""
    monkeypatch.setenv("YOKE_ONBOARD_FORCE_PLAIN", "0")
