"""Installed commit refusals keep checks enabled and teach recovery."""

from __future__ import annotations

import inspect

from yoke_harness.git_hooks import pre_commit


def test_commit_gate_never_contains_bypass_advice():
    assert "--no-verify" not in inspect.getsource(pre_commit)
