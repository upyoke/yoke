# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse

from yoke_core.engines import merge_worktree as mw

from yoke_core.engines import merge_worktree_prepare as prep

from yoke_core.engines import merge_worktree_prepare_preflight as pf

from yoke_core.engines.merge_worktree_prepare import (
    MergeArgs as MergeArgs,
    MergeContext as MergeContext,
)

TEST_ITEM_ID = 42

TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _no_bare_db(monkeypatch):
    """Fail the test if any migrated path opens a bare connect / subprocess."""
    monkeypatch.setattr(
        mw,
        "_connect",
        lambda *_a, **_k: pytest.fail("must not open a bare mw._connect()"),
    )
    monkeypatch.setattr(
        mw,
        "_run_python_module",
        lambda *_a, **_k: pytest.fail("must not shell out via _run_python_module"),
    )
