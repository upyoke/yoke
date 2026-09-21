"""Project carried-work warnings that change what a run can attest.

``honest_carried_shas`` refuses those payloads; this module names the
warning, the commits the run can no longer vouch for, the ancestry
residual fallback, and the recovery — for the deploy pipeline and for
``deployment_runs.get``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.json_helper import loads_text

CHECKOUT_NOT_REFRESHED = "checkout_not_refreshed"
#: Stored payloads name the reason only. New writers may also set
#: ``changes_attestation``; surfacing walks whichever warnings actually
#: change what ``honest_carried_shas`` will vouch for.
ATTESTATION_CHANGING_REASONS = frozenset({CHECKOUT_NOT_REFRESHED})
ATTESTATION_WARNINGS_FIELD = "attestation_warnings"
_DEFAULT_ATTESTATION_RECOVERY = (
    "Refresh the checkout that derived carried work and re-drive the run "
    "so it records an honest payload, then retry."
)


def _payload_from(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    parsed = loads_text(str(raw or "{}"))
    return parsed if isinstance(parsed, dict) else {}


def _payload_slices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    slices = [payload]
    for entry in payload.get("bound_projects") or []:
        if isinstance(entry, dict):
            slices.append(entry)
    return slices


def _warning_reason(warning: Any) -> str:
    if isinstance(warning, Mapping):
        return str(warning.get("reason") or "").strip()
    return str(warning or "").strip()


def _warning_recovery(warning: Any) -> str:
    if isinstance(warning, Mapping):
        text = str(warning.get("recovery") or "").strip()
        if text:
            return text
    return _DEFAULT_ATTESTATION_RECOVERY


def warning_changes_attestation(warning: Any) -> bool:
    if isinstance(warning, Mapping):
        flagged = warning.get("changes_attestation")
        if flagged is True:
            return True
        if flagged is False:
            return False
    return _warning_reason(warning) in ATTESTATION_CHANGING_REASONS


def has_attestation_changing_warning(payload: dict[str, Any]) -> bool:
    return any(
        warning_changes_attestation(warning)
        for warning in payload.get("warnings") or []
    )


def _named_shas_in(payload: dict[str, Any]) -> set[str]:
    carried: set[str] = set()
    for entry in payload.get("items") or []:
        if not isinstance(entry, dict):
            continue
        for sha in entry.get("commit_shas") or []:
            text = str(sha or "").strip()
            if text:
                carried.add(text)
    return carried


def named_carried_shas(
    raw: Any,
    *,
    bound_project_id: int | None = None,
) -> set[str]:
    """Commits one run named, whether or not it can still vouch for them."""
    payload = _payload_from(raw)
    if bound_project_id is not None:
        slice_payload = next(
            (
                entry
                for entry in payload.get("bound_projects") or []
                if isinstance(entry, dict)
                and entry.get("project_id") == bound_project_id
            ),
            {},
        )
        if not isinstance(slice_payload, dict):
            return set()
        return _named_shas_in(slice_payload)
    named: set[str] = set()
    for slice_payload in _payload_slices(payload):
        named.update(_named_shas_in(slice_payload))
    return named


def _attestation_cost(named: set[str]) -> str:
    if not named:
        return (
            "This run can no longer vouch for a carried commit set; "
            "item delivery attribution falls back to the ancestry residual."
        )
    listed = ", ".join(sorted(named))
    n = len(named)
    noun = "commit" if n == 1 else "commits"
    return (
        f"This run named {n} {noun} it can no longer vouch for "
        f"({listed}); item delivery attribution falls back to the "
        "ancestry residual."
    )


def attestation_warnings(raw: Any) -> list[dict[str, str]]:
    """Warnings that change what the run can attest, with cost and recovery."""
    payload = _payload_from(raw)
    if not payload:
        return []
    cost = _attestation_cost(named_carried_shas(payload))
    seen: set[tuple[str, str]] = set()
    projected: list[dict[str, str]] = []
    for slice_payload in _payload_slices(payload):
        for warning in slice_payload.get("warnings") or []:
            if not warning_changes_attestation(warning):
                continue
            reason = _warning_reason(warning) or "unspecified"
            recovery = _warning_recovery(warning)
            key = (reason, recovery)
            if key in seen:
                continue
            seen.add(key)
            projected.append({"reason": reason, "cost": cost, "recovery": recovery})
    return projected


def attestation_warning_lines(raw: Any) -> list[str]:
    """Deploy-pipeline lines for attestation-changing carried-work warnings."""
    return [
        (
            f"carried-work attestation: {item['reason']} — {item['cost']} "
            f"Recovery: {item['recovery']}"
        )
        for item in attestation_warnings(raw)
    ]


__all__ = [
    "ATTESTATION_CHANGING_REASONS",
    "ATTESTATION_WARNINGS_FIELD",
    "CHECKOUT_NOT_REFRESHED",
    "attestation_warning_lines",
    "attestation_warnings",
    "has_attestation_changing_warning",
    "named_carried_shas",
    "warning_changes_attestation",
]
