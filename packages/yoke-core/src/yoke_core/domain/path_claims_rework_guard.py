"""Shared Bash and edit refusal when landing released an item's claims."""

from __future__ import annotations

from yoke_core.domain.path_claims_landing import needs_rework_coverage
from yoke_core.domain.project_identity import render_item_ref


REWORK_COVERAGE_REQUIRED = "rework-coverage-required"


def recovery(public_ref: str) -> str:
    return (
        "path_claim_rework_coverage_required: landing released this item's coverage. "
        "Before lane edits, register the complete rework touch set with "
        f"`yoke claims path register --item {public_ref} "
        "--paths <comma-separated paths> --allow-planned`, then prepare the lane "
        "to activate it. A per-task Epic adds `--task-num <N>` for the landed "
        "task the rework changes; its other landed tasks need no new claim. "
        "Released claims cannot be widened or reactivated."
    )


def missing_rework_claim(conn, *, item_id: int, paths: dict) -> dict | None:
    if not needs_rework_coverage(conn, item_id):
        return None
    return {
        **paths,
        "owner_item_id": item_id,
        "public_ref": render_item_ref(conn, item_id),
        "state": REWORK_COVERAGE_REQUIRED,
        "covered_paths": [],
    }
