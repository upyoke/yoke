"""Reject ended or stale-version broker bindings before acceptance preview.

Preview used to trust the operator-supplied pair and report ready. After a
codex-cli rollover those rows stay selectable while ended and registered on
the previous version, so the live cell failed on a binding preview already
had enough evidence to refuse.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from yoke_contracts.session_control.surface_versions import surface_version_meets_floor


ENDED_CODE = "broker_binding_ended_session"
STALE_CODE = "broker_binding_stale_version"
ENDED_RECOVERY = (
    "Bind a live current-version same-machine broker target and peer, "
    "then rerun preview."
)
STALE_RECOVERY = (
    "Bind sessions registered at the relay-advertised current version "
    "on the same machine, then rerun preview."
)


@dataclass(frozen=True)
class BrokerBinding:
    target_session_id: str
    machine_id: str
    peer_session_id: str


@dataclass(frozen=True)
class BrokerBindingDecision:
    status: str
    binding: BrokerBinding
    failure_code: str | None = None
    recovery: str | None = None
    advertised_version: str = ""


def advertised_version_from_preview(preview: Mapping[str, Any], fallback: str) -> str:
    selected = preview.get("selected_relay")
    if isinstance(selected, dict):
        version = str(selected.get("version") or "").strip()
        if version:
            return version
    return str(fallback or "").strip()


def _session_id(row: Mapping[str, Any] | None) -> str:
    if row is None:
        return ""
    return str(row.get("session_id") or "").strip()


def binding_session_ended(row: Mapping[str, Any] | None) -> bool:
    if row is None:
        return True
    if row.get("terminated_at"):
        return True
    return str(row.get("liveness") or "ended") == "ended"


def binding_version_stale(
    row: Mapping[str, Any] | None,
    *,
    surface: str,
    advertised_version: str,
) -> bool:
    if row is None or not advertised_version:
        return True
    registered = str(row.get("executor_version") or "").strip()
    return not surface_version_meets_floor(surface, registered, advertised_version)


def _current_live(
    row: Mapping[str, Any] | None,
    *,
    surface: str,
    advertised_version: str,
    machine_id: str,
) -> bool:
    if row is None or binding_session_ended(row):
        return False
    if str(row.get("machine_id") or "") != machine_id:
        return False
    if str(row.get("executor_surface") or "") != surface:
        return False
    return not binding_version_stale(
        row, surface=surface, advertised_version=advertised_version
    )


def _first_defect(
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    *,
    surface: str,
    advertised_version: str,
) -> tuple[str, str]:
    if binding_session_ended(target) or binding_session_ended(peer):
        return ENDED_CODE, ENDED_RECOVERY
    if binding_version_stale(
        target, surface=surface, advertised_version=advertised_version
    ) or binding_version_stale(
        peer, surface=surface, advertised_version=advertised_version
    ):
        return STALE_CODE, STALE_RECOVERY
    return STALE_CODE, STALE_RECOVERY


def _pick_unused(
    candidates: Sequence[Mapping[str, Any]], used: set[str]
) -> Mapping[str, Any] | None:
    for row in candidates:
        session_id = _session_id(row)
        if session_id and session_id not in used:
            return row
    return None


def select_current_broker_binding(
    binding: BrokerBinding,
    *,
    surface: str,
    advertised_version: str,
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
) -> BrokerBinding | None:
    """Prefer a live current-version same-machine pair; never reuse a stale row."""
    usable = sorted(
        (
            row
            for row in candidates
            if _current_live(
                row,
                surface=surface,
                advertised_version=advertised_version,
                machine_id=binding.machine_id,
            )
        ),
        key=_session_id,
    )
    keep_target = (
        target
        if _current_live(
            target,
            surface=surface,
            advertised_version=advertised_version,
            machine_id=binding.machine_id,
        )
        else None
    )
    keep_peer = (
        peer
        if _current_live(
            peer,
            surface=surface,
            advertised_version=advertised_version,
            machine_id=binding.machine_id,
        )
        else None
    )
    used = {_session_id(keep_target), _session_id(keep_peer)} - {""}
    if keep_target is None:
        keep_target = _pick_unused(usable, used)
        if keep_target is None:
            return None
        used.add(_session_id(keep_target))
    if keep_peer is None:
        keep_peer = _pick_unused(usable, used)
        if keep_peer is None:
            return None
    target_id = _session_id(keep_target)
    peer_id = _session_id(keep_peer)
    if not target_id or not peer_id or target_id == peer_id:
        return None
    return BrokerBinding(target_id, binding.machine_id, peer_id)


def decide_broker_binding(
    binding: BrokerBinding,
    *,
    surface: str,
    advertised_version: str,
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]] = (),
) -> BrokerBindingDecision:
    """Ready only when the named pair — or a selected replacement — is live."""
    selected = select_current_broker_binding(
        binding,
        surface=surface,
        advertised_version=advertised_version,
        target=target,
        peer=peer,
        candidates=candidates,
    )
    if selected is not None:
        return BrokerBindingDecision(
            "ready", selected, advertised_version=advertised_version
        )
    code, recovery = _first_defect(
        target, peer, surface=surface, advertised_version=advertised_version
    )
    return BrokerBindingDecision(
        "not_ready",
        binding,
        failure_code=code,
        recovery=recovery,
        advertised_version=advertised_version,
    )


def _one_row(
    client: CommandClient, *, project: str, session_id: str
) -> dict[str, Any] | None:
    result = client.call(
        ["sessions", "list", "--project", project, "--session", session_id]
    )
    rows = result.get("rows")
    matches = (
        [
            row
            for row in rows
            if isinstance(row, dict) and row.get("session_id") == session_id
        ]
        if isinstance(rows, list)
        else []
    )
    return matches[0] if len(matches) == 1 else None


def _active_candidates(
    client: CommandClient, *, project: str
) -> tuple[dict[str, Any], ...]:
    result = client.call(
        ["sessions", "list", "--project", project, "--liveness", "active"]
    )
    rows = result.get("rows")
    if not isinstance(rows, list):
        return ()
    return tuple(row for row in rows if isinstance(row, dict))


def resolve_broker_binding(
    client: CommandClient,
    *,
    project: str,
    surface: str,
    binding: BrokerBinding,
    expected_version: str,
) -> BrokerBindingDecision:
    """Read launch preview and roster, then decide the broker pair."""
    preview = client.call(
        [
            "sessions",
            "create",
            "--project",
            project,
            "--surface",
            surface,
            "--machine",
            binding.machine_id,
            "--preview",
        ]
    )
    advertised = advertised_version_from_preview(preview, expected_version)
    return decide_broker_binding(
        binding,
        surface=surface,
        advertised_version=advertised,
        target=_one_row(client, project=project, session_id=binding.target_session_id),
        peer=_one_row(client, project=project, session_id=binding.peer_session_id),
        candidates=_active_candidates(client, project=project),
    )


def preview_document(
    *,
    run_id: str,
    release_sha: str,
    project: str,
    cells: Sequence[Mapping[str, Any]],
    decision: BrokerBindingDecision,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": 1,
        "kind": "fleet_session_control_live_acceptance_preview",
        "run_id": run_id,
        "release_sha": release_sha,
        "project": project,
        "cells": list(cells),
        "status": "ready" if decision.status == "ready" else "not_ready",
    }
    if decision.status != "ready":
        document["failure_code"] = decision.failure_code
        document["recovery"] = decision.recovery
    return document


def dumps_preview(**payload: Any) -> str:
    return json.dumps(
        preview_document(**payload), sort_keys=True, separators=(",", ":")
    )


def refuse_unready_broker(decision: BrokerBindingDecision, *, surface: str) -> None:
    if decision.status == "ready":
        return
    raise AcceptanceContractError(
        decision.failure_code or ENDED_CODE,
        surface=surface,
        evidence={"recovery": decision.recovery},
    )


__all__ = [
    "ENDED_CODE",
    "ENDED_RECOVERY",
    "STALE_CODE",
    "STALE_RECOVERY",
    "BrokerBinding",
    "BrokerBindingDecision",
    "advertised_version_from_preview",
    "binding_session_ended",
    "binding_version_stale",
    "decide_broker_binding",
    "dumps_preview",
    "preview_document",
    "refuse_unready_broker",
    "resolve_broker_binding",
    "select_current_broker_binding",
]
