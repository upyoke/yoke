"""Teaching-audit coverage for readiness wrapper recipes."""

from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_RAW_FORMS = (
    "python3 -m yoke_core.domain.idea_readiness_check",
    "python3 -m yoke_core.domain.idea_readiness_repair",
    "python3 -m yoke_core.domain.idea_readiness_repair_claim_coverage",
    "python3 -m yoke_core.domain.path_claim_required_gate",
    "python3 -m yoke_core.domain.advance_path_claim_activation",
)


def test_readiness_teaching_uses_registered_surfaces() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)
    by_form = {row.command_form: row for row in audit.surfaces}

    for command_form in (
        "yoke readiness check",
        "yoke readiness repair-stale-count",
        "yoke readiness repair-claim-coverage",
        "yoke claims path required-gate",
        "yoke claims path activation-run",
    ):
        row = by_form[command_form]
        assert row.resolution == "registered"
        assert row.drift_type is None

    for row in audit.surfaces:
        assert not row.command_form.startswith(TARGET_RAW_FORMS), row
        assert row.drift_type != teaching.DRIFT_UNSANCTIONED_INTERNAL or (
            not row.command_form.startswith(TARGET_RAW_FORMS)
        )
