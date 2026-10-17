"""Mocked primitives the ``runs start-for-item`` composer wraps.

The composer resolves the target, then creates the run with its item enrolled
and composition validated in one transaction. Every test of it stubs those
steps so the surface stays deterministic and needs no live GitHub or
deployment service; sharing the stubs keeps one description of what the
composer sits on top of.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.domain.deployment_run_create_write import CreatedRun
from yoke_core.engines import runs_start_for_item as composer


def _patches(
    *,
    item_row=("yoke", "to-prod"),
    target=("persistent", 101, "prod"),
    run_id="2026-05-19-001",
    validation_message="ok",
    resolve_raises=None,
    create_raises=None,
):
    """Return a tuple of mock patches covering the composer's helpers."""
    helpers = mock.patch.object(
        composer,
        "_lookup_item_project_and_flow",
        return_value=item_row,
    )
    resolve = mock.patch.object(
        composer,
        "cmd_resolve_target",
        side_effect=resolve_raises if resolve_raises else None,
        return_value=target,
    )
    tested = mock.patch.object(composer, "require_tested_lineage", return_value=None)
    create = mock.patch.object(
        composer,
        "create_run",
        side_effect=create_raises if create_raises else None,
        return_value=CreatedRun(run_id, False, None, validation_message),
    )
    return helpers, resolve, tested, create


__all__ = ["_patches"]
