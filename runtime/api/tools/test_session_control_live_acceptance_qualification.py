"""One-shot grant tests for private-version live acceptance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from runtime.api.tools import session_control_live_acceptance as acceptance
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
    acceptance_operation,
)
from runtime.api.tools.session_control_live_acceptance_qualification import (
    OpenedQualification,
    QualificationCoordinator,
)
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_RELEASE_REASON,
    PrivateRouteQualificationScope,
)


RELEASE_SHA = "a" * 40
# Version evidence already authorizes this surface's stopped-session wake, so
# its acceptance route needs no one-shot qualification.
PROVEN_WAKE_CELL = AcceptanceCell(
    "claude-cli",
    "2.1.241",
    "create",
    acceptance_role="surface",
    wake_route="direct",
)
# The active-message route stays private, and this version is outside the exact
# pin that qualifies it, so acceptance must open a one-shot grant for it.
UNPROVEN_PRIVATE_ROUTE_CELL = AcceptanceCell(
    "claude-desktop",
    "1.34493.1",
    "identify",
    session_id="desktop-session",
    acceptance_role="surface",
    wake_route="none",
)


class _Client:
    def __init__(
        self,
        *,
        forged_sender: bool = False,
        forged_release_session: bool = False,
        forged_release_actor: bool = False,
        include_history: bool = False,
    ) -> None:
        self.forged_sender = forged_sender
        self.forged_release_session = forged_release_session
        self.forged_release_actor = forged_release_actor
        self.include_history = include_history
        self.opened: list[tuple[PrivateRouteQualificationScope, int]] = []
        self.calls: list[tuple[str, ...]] = []
        self.consumed = True

    def call(self, args, *, stdin=None):
        assert stdin is None
        tokens = tuple(args)
        self.calls.append(tokens)
        if tokens[:3] == ("session-control", "qualification", "open"):
            values = {
                tokens[index]: tokens[index + 1] for index in range(3, len(tokens), 2)
            }
            scope = PrivateRouteQualificationScope(
                release_sha=values["--release-sha"],
                acceptance_run_id=values["--run-id"],
                surface=values["--surface"],
                version=values["--version"],
                operation=values["--operation"],
                route=values["--route"],
            )
            lease_id = 100 + len(self.opened)
            self.opened.append((scope, lease_id))
            opened = datetime.now(timezone.utc)
            return {
                "grant": {
                    "lease_id": lease_id,
                    "project_id": 1,
                    "sender_session_id": (
                        "forged-session" if self.forged_sender else "main-session"
                    ),
                    "operator_actor_id": "169",
                    "opened_at": opened.isoformat(),
                    "expires_at": (opened + timedelta(minutes=30)).isoformat(),
                    "grant_digest": scope.digest,
                    "scope": scope.model_dump(mode="json"),
                }
            }
        if tokens[:2] == ("coordination-lease", "list"):
            lease_key = tokens[tokens.index("--key") + 1]
            scope, lease_id = next(
                pair for pair in self.opened if pair[0].lease_key == lease_key
            )
            current = {
                "id": lease_id,
                "lease_key": scope.lease_key,
                "released_at": "2026-08-23T01:00:00Z" if self.consumed else None,
                "release_reason": (
                    QUALIFICATION_RELEASE_REASON if self.consumed else None
                ),
                "released_by_session_id": (
                    "forged-session" if self.forged_release_session else "main-session"
                ),
                "released_by_actor_id": ("999" if self.forged_release_actor else "169"),
            }
            history = (
                [{"id": lease_id - 20, "lease_key": scope.lease_key}]
                if self.include_history
                else []
            )
            return {"leases": [*history, current]}
        raise AssertionError(tokens)


def _matrix() -> AcceptanceMatrix:
    return AcceptanceMatrix(
        project="yoke",
        cells=(
            PROVEN_WAKE_CELL,
            UNPROVEN_PRIVATE_ROUTE_CELL,
            AcceptanceCell(
                "codex-cli",
                "0.148.0-alpha.15",
                "create",
                acceptance_role="surface",
                wake_route="direct",
            ),
        ),
    )


def _open_acceptance_route(
    coordinator: QualificationCoordinator, cell: AcceptanceCell
) -> OpenedQualification | None:
    """Open at the boundary of the operation this surface is accepted on."""
    return coordinator.open(cell, acceptance_operation(cell.surface))


def test_candidate_grants_are_exact_redacted_and_consumed() -> None:
    client = _Client()
    matrix = _matrix()
    coordinator = QualificationCoordinator(
        client,
        matrix,
        run_id="stage-proof-1",
        release_sha=RELEASE_SHA,
        caller_session_id="main-session",
    )
    assert client.opened == []

    authorized = _open_acceptance_route(coordinator, PROVEN_WAKE_CELL)
    opened = _open_acceptance_route(coordinator, UNPROVEN_PRIVATE_ROUTE_CELL)

    assert authorized is None
    assert opened is not None
    assert (opened.grant.scope.operation, opened.grant.scope.route) == (
        "message_active",
        "hook",
    )
    assert opened.grant.scope.surface == UNPROVEN_PRIVATE_ROUTE_CELL.surface
    assert opened.grant.scope.version == UNPROVEN_PRIVATE_ROUTE_CELL.expected_version
    assert opened.grant.scope.environment == "stage"
    assert len(client.opened) == 1
    evidence = coordinator.evidence()
    assert [set(entry) for entry in evidence] == [{"lease_id", "grant_digest"}]
    assert "lease_key" not in repr(evidence)

    coordinator.verify(opened)
    assert coordinator.all_consumed is True


def test_forged_sender_grant_is_refused_before_acceptance() -> None:
    matrix = _matrix()
    coordinator = QualificationCoordinator(
        _Client(forged_sender=True),
        matrix,
        run_id="stage-proof-2",
        release_sha=RELEASE_SHA,
        caller_session_id="main-session",
    )
    with pytest.raises(AcceptanceContractError) as raised:
        _open_acceptance_route(coordinator, UNPROVEN_PRIVATE_ROUTE_CELL)

    assert raised.value.code == "qualification_grant_mismatch"


def test_unconsumed_grant_fails_the_acceptance_gate() -> None:
    client = _Client()
    matrix = _matrix()
    coordinator = QualificationCoordinator(
        client,
        matrix,
        run_id="stage-proof-3",
        release_sha=RELEASE_SHA,
        caller_session_id="main-session",
    )
    opened = _open_acceptance_route(coordinator, UNPROVEN_PRIVATE_ROUTE_CELL)
    client.consumed = False

    with pytest.raises(AcceptanceContractError) as raised:
        coordinator.verify(opened)

    assert raised.value.code == "qualification_not_consumed"
    assert coordinator.all_consumed is False


def test_exact_lease_is_verified_among_prior_scope_history() -> None:
    client = _Client(include_history=True)
    matrix = _matrix()
    coordinator = QualificationCoordinator(
        client,
        matrix,
        run_id="stage-proof-history",
        release_sha=RELEASE_SHA,
        caller_session_id="main-session",
    )
    opened = _open_acceptance_route(coordinator, UNPROVEN_PRIVATE_ROUTE_CELL)
    assert opened is not None

    coordinator.verify(opened)

    assert coordinator.all_consumed is True


@pytest.mark.parametrize(
    "client",
    [
        _Client(forged_release_session=True),
        _Client(forged_release_actor=True),
    ],
)
def test_forged_release_identity_cannot_prove_consumption(client: _Client) -> None:
    matrix = _matrix()
    coordinator = QualificationCoordinator(
        client,
        matrix,
        run_id="stage-proof-forged-release",
        release_sha=RELEASE_SHA,
        caller_session_id="main-session",
    )
    opened = _open_acceptance_route(coordinator, UNPROVEN_PRIVATE_ROUTE_CELL)

    with pytest.raises(AcceptanceContractError) as raised:
        coordinator.verify(opened)

    assert raised.value.code == "qualification_not_consumed"


def test_candidate_runner_keeps_stage_pinned_after_active_env_switch(
    monkeypatch,
    capsys,
) -> None:
    selected = {"environment": "stage"}
    matrix = AcceptanceMatrix(project="yoke", cells=(UNPROVEN_PRIVATE_ROUTE_CELL,))
    captured: dict[str, object] = {}

    class _PinnedClient:
        def __init__(self, *, explicit_env: str) -> None:
            self.explicit_env = explicit_env
            captured["explicit_env"] = explicit_env

        def deployed_release(self) -> dict[str, str]:
            selected["environment"] = "prod"
            return {"server_build": RELEASE_SHA, "engine_version": "0.1.1"}

        def call(self, args, *, stdin=None):
            captured["mutating_call"] = (self.explicit_env, tuple(args), stdin)
            return {}

    class _Driver:
        def __init__(self, client) -> None:
            self.client = client

        def run(self, _matrix, **_kwargs):
            assert selected["environment"] == "prod"
            self.client.call(["sessions", "create"])
            return {
                "schema": 1,
                "kind": "fleet_session_control_live_acceptance",
                "status": "passed",
                "cells": [],
            }

    monkeypatch.setattr(acceptance, "_is_subagent_execution", lambda: False)
    monkeypatch.setattr(acceptance, "_caller_session_id", lambda: "main-session")
    monkeypatch.setattr(
        acceptance.machine_config,
        "active_env",
        lambda: selected["environment"],
    )

    def _connection(*, explicit_env=None):
        assert explicit_env == "stage"
        return {"transport": "https", "prod": False}

    monkeypatch.setattr(acceptance.machine_config, "active_connection", _connection)
    monkeypatch.setattr(acceptance, "load_candidate_matrix", lambda _path: matrix)
    monkeypatch.setattr(acceptance, "YokeCliClient", _PinnedClient)
    monkeypatch.setattr(acceptance, "LiveAcceptanceDriver", _Driver)

    code = acceptance.main(
        [
            "--qualification-candidate",
            "--matrix",
            "candidate.json",
            "--run-id",
            "stage-env-pin",
            "--release-sha",
            RELEASE_SHA,
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["status"] == "passed"
    assert captured["explicit_env"] == "stage"
    assert captured["mutating_call"] == (
        "stage",
        ("sessions", "create"),
        None,
    )
