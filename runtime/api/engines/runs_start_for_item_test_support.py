"""Mocked primitives the ``runs start-for-item`` composer wraps.

The composer folds resolve-target, create-run, add-item, and
validate-composition into one call. Every test of it stubs those four so
the surface stays deterministic and needs no live GitHub or deployment
service; sharing the stubs keeps one description of what the composer
sits on top of.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.engines import runs_start_for_item as composer


def _patches(
    *,
    item_row=("yoke", "to-prod"),
    target=("persistent", 101, "prod"),
    run_id="2026-05-19-001",
    add_item_ret="OK",
    validate_ret=(True, "ok"),
    resolve_raises=None,
    create_raises=None,
    add_raises=None,
    validate_raises=None,
):
    """Return a tuple of mock patches covering the composer's helpers."""
    helpers = mock.patch.object(
        composer,
        "_lookup_item_project_and_flow",
        return_value=item_row,
    )
    resolve = mock.patch.object(
        composer, "cmd_resolve_target",
        side_effect=resolve_raises if resolve_raises else None,
        return_value=target,
    )
    create = mock.patch.object(
        composer, "cmd_create_run",
        side_effect=create_raises if create_raises else None,
        return_value=run_id,
    )
    add = mock.patch.object(
        composer, "cmd_add_item",
        side_effect=add_raises if add_raises else None,
        return_value=add_item_ret,
    )
    validate = mock.patch.object(
        composer, "cmd_validate_composition",
        side_effect=validate_raises if validate_raises else None,
        return_value=validate_ret,
    )
    return helpers, resolve, create, add, validate


__all__ = ["_patches"]
