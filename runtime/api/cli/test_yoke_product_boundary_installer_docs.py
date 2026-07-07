from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]
TARGET_DOCS = {
    "docs/event-contract.md",
    "docs/event-contract/migration-guidance.md",
    "docs/event-contract/reserved-fields-dr1-qa1.md",
    "docs/onboard-external-project.md",
}
HIDDEN_ONBOARDING_TERMS = (
    "yoke_core.domain.api_tokens_cli",
    "yoke_core.domain.actor_grants_cli",
)


def test_installer_docs_do_not_teach_hidden_internal_recipes() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)

    offenders = [
        row for row in audit.surfaces
        if row.source in TARGET_DOCS
        and row.drift_type == teaching.DRIFT_UNSANCTIONED_INTERNAL
    ]

    assert offenders == []


def test_event_docs_use_registered_emit_surface() -> None:
    audit = inventory.generate_teaching_audit(repo_root=REPO_ROOT)

    emit_rows = [
        row for row in audit.surfaces
        if row.source in TARGET_DOCS
        and row.command_form == "yoke events emit"
    ]

    assert emit_rows
    assert {row.resolution for row in emit_rows} == {"registered"}
    assert {row.drift_type for row in emit_rows} == {None}


def test_external_onboarding_keeps_admin_modules_out_of_product_path() -> None:
    body = (REPO_ROOT / "docs/onboard-external-project.md").read_text(
        encoding="utf-8"
    )

    for term in HIDDEN_ONBOARDING_TERMS:
        assert term not in body
    assert "source-dev/admin boundary" in body
