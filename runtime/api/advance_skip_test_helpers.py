"""Shared helpers for the advance_skip test modules.

Used by both ``test_advance_skip.py`` (skip-polish path) and
``test_advance_skip_refine.py`` (skip-refine path). No tests live here —
the lack of a ``test_`` prefix keeps pytest from collecting it.
"""

from __future__ import annotations

import os
from unittest import mock

from yoke_core.domain import advance_skip_core
from yoke_core.domain import advance_skip_finalize


class _CallRecorder:
    """Track every ``_do_execute_update`` invocation and inspect env during the call."""

    def __init__(self):
        self.calls: list[tuple[int, str]] = []
        self.bypass_seen: list[str] = []
        self.source_seen: list[str] = []
        self.rebuild_board_seen: list[bool] = []

    def __call__(self, item_id, status, out, *, rebuild_board=True):
        self.calls.append((item_id, status))
        self.bypass_seen.append(os.environ.get("YOKE_CLAIM_BYPASS", ""))
        self.source_seen.append(os.environ.get("YOKE_STATUS_SOURCE", ""))
        self.rebuild_board_seen.append(rebuild_board)
        return {"success": True}


def _patch_core(
    current_status: str,
    item_type: str = "issue",
    *,
    executor=None,
    emit_recorder=None,
    release_recorder=None,
):
    """Return an ExitStack-like object that patches advance_skip seams."""
    patches = []
    patches.append(
        mock.patch.object(
            advance_skip_core,
            "_lookup_item",
            return_value=(current_status, item_type),
        )
    )
    patches.append(
        mock.patch.object(
            advance_skip_core, "_do_execute_update", executor or _CallRecorder()
        )
    )
    if emit_recorder is not None:
        patches.append(
            mock.patch.object(advance_skip_finalize, "_emit_skip_event", emit_recorder)
        )
    else:
        patches.append(
            mock.patch.object(
                advance_skip_finalize,
                "_emit_skip_event",
                lambda *a, **kw: None,
            )
        )
    if release_recorder is not None:
        patches.append(
            mock.patch.object(advance_skip_finalize, "_release_claim", release_recorder)
        )
    else:
        patches.append(
            mock.patch.object(
                advance_skip_finalize,
                "_release_claim",
                lambda *a, **kw: {"released": False, "reason": "no_active_claim"},
            )
        )
    return patches


def _enter_all(patches):
    return [p.__enter__() for p in patches]


def _exit_all(patches):
    for p in reversed(patches):
        p.__exit__(None, None, None)
