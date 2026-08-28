"""Resolve broker bindings before Fleet acceptance preview or execution."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from runtime.api.tools.session_control_live_acceptance_broker_eligibility import (
    NO_CLAIM_FREE_PAIR_CODE,
    BrokerBinding,
    BrokerBindingDecision,
    decide_broker_binding,
)
from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)


def advertised_version_from_preview(preview: Mapping[str, Any], fallback: str) -> str:
    selected = preview.get("selected_relay")
    if isinstance(selected, dict):
        version = str(selected.get("version") or "").strip()
        if version:
            return version
    return str(fallback or "").strip()


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
        project=project,
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
        # Name what was weighed and how each candidate failed, per role, so the
        # next operator reads the failing axis instead of re-deriving it against
        # a roster that has already moved on.
        document["considered_sessions"] = [dict(row) for row in decision.considered]
    return document


def dumps_preview(**payload: Any) -> str:
    return json.dumps(
        preview_document(**payload), sort_keys=True, separators=(",", ":")
    )


def refuse_unready_broker(decision: BrokerBindingDecision, *, surface: str) -> None:
    if decision.status == "ready":
        return
    raise AcceptanceContractError(
        decision.failure_code or NO_CLAIM_FREE_PAIR_CODE,
        surface=surface,
        evidence={
            "recovery": decision.recovery,
            "considered_sessions": [dict(row) for row in decision.considered],
        },
    )


__all__ = [
    "BrokerBinding",
    "BrokerBindingDecision",
    "advertised_version_from_preview",
    "dumps_preview",
    "preview_document",
    "refuse_unready_broker",
    "resolve_broker_binding",
]
