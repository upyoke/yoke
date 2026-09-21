"""Carried-work warnings that change what a run can attest.

Honest carriage still refuses those payloads. These cases prove the
projection names the warning, the commits the run can no longer vouch
for, the ancestry residual, and the recovery — and stays silent for
cosmetic warnings.
"""

from __future__ import annotations

import json

from yoke_core.domain.release_delivery_attestation import (
    attestation_warning_lines,
    attestation_warnings,
    named_carried_shas,
)
from yoke_core.domain.release_delivery_membership import honest_carried_shas

SHA = "a" * 40
RECOVERY = (
    "Checkout /repo answered from the refs it already held "
    "(fetching origin failed); a commit recorded after its last "
    "fetch reads as unreachable."
)


def _stale(*, extra_warning: dict | None = None) -> dict:
    warnings: list[dict] = [
        {"reason": "checkout_not_refreshed", "recovery": RECOVERY},
    ]
    if extra_warning is not None:
        warnings.append(extra_warning)
    return {
        "derivation": {"contents_known": True},
        "items": [{"ref": "YOK-1", "commit_shas": [SHA]}],
        "warnings": warnings,
    }


def test_checkout_not_refreshed_projects_reason_cost_and_recovery() -> None:
    projected = attestation_warnings(_stale())
    assert len(projected) == 1
    item = projected[0]
    assert item["reason"] == "checkout_not_refreshed"
    assert SHA in item["cost"]
    assert "ancestry residual" in item["cost"]
    assert item["recovery"] == RECOVERY
    assert honest_carried_shas(json.dumps(_stale())) == set()
    assert named_carried_shas(_stale()) == {SHA}


def test_flagged_warning_is_projected_without_special_casing_its_reason() -> None:
    payload = {
        "derivation": {"contents_known": True},
        "items": [{"commit_shas": [SHA]}],
        "warnings": [
            {
                "reason": "source_graph_incomplete",
                "changes_attestation": True,
                "recovery": "Restore the compare listing, then retry.",
            }
        ],
    }
    projected = attestation_warnings(payload)
    assert projected[0]["reason"] == "source_graph_incomplete"
    assert SHA in projected[0]["cost"]
    assert projected[0]["recovery"] == "Restore the compare listing, then retry."
    assert honest_carried_shas(json.dumps(payload)) == set()


def test_cosmetic_warning_does_not_surface_or_dishonest_carriage() -> None:
    payload = {
        "derivation": {"contents_known": True},
        "items": [{"commit_shas": [SHA]}],
        "warnings": [
            {
                "reason": "lane_branch_refs_unresolvable",
                "recovery": "attribution used recorded evidence instead.",
            }
        ],
    }
    assert attestation_warnings(payload) == []
    assert attestation_warning_lines(payload) == []
    assert honest_carried_shas(json.dumps(payload)) == {SHA}


def test_no_warnings_project_nothing() -> None:
    payload = {
        "derivation": {"contents_known": True},
        "items": [{"commit_shas": [SHA]}],
        "warnings": [],
    }
    assert attestation_warnings(payload) == []
    assert attestation_warning_lines(None) == []
    assert honest_carried_shas(json.dumps(payload)) == {SHA}
