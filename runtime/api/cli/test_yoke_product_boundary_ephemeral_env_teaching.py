"""Teaching-audit coverage for ephemeral environment update wrappers."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_ENV_UPDATE = "python3 -m yoke_core.cli.db_router envs update"


def test_ephemeral_env_teaching_uses_registered_update_surface() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)
    by_form = {row.command_form: row for row in audit.surfaces}

    row = by_form["yoke ephemeral-env update"]
    assert row.function_id == "ephemeral_env.update"
    assert row.resolution == "registered"
    assert row.drift_type is None

    for surface in audit.surfaces:
        assert not surface.command_form.startswith(RAW_ENV_UPDATE), surface
        assert surface.drift_type != teaching.DRIFT_UNSANCTIONED_INTERNAL or (
            not surface.command_form.startswith(RAW_ENV_UPDATE)
        )
