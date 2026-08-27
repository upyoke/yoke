"""Open and settle one-shot stage qualifications around live acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from runtime.api.tools.session_control_live_acceptance_client import CommandClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
    AcceptanceMatrix,
    acceptance_operation,
)
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_RELEASE_REASON,
    PrivateRouteQualificationGrant,
    PrivateRouteQualificationScope,
)
from yoke_contracts.session_control.surface_versions import surface_operation_supported


@dataclass(frozen=True)
class OpenedQualification:
    grant: PrivateRouteQualificationGrant


def _route(cell: AcceptanceCell, operation: str, route: str | None) -> str:
    """Qualify the route actually exercised, never the cell's authored label.

    A broker-capable cell carries no fixed route, so its caller resolves the
    plane's live selection first and passes it here.
    """
    if operation == "message_active":
        return "hook"
    resolved = route or cell.route
    if resolved not in {"direct", "broker"}:
        raise AcceptanceContractError(
            "qualification_route_invalid", surface=cell.surface
        )
    return resolved


def _open_one(
    client: CommandClient,
    *,
    project: str,
    caller_session_id: str,
    scope: PrivateRouteQualificationScope,
) -> OpenedQualification:
    result = client.call(
        [
            "session-control",
            "qualification",
            "open",
            "--project",
            project,
            "--release-sha",
            scope.release_sha,
            "--run-id",
            scope.acceptance_run_id,
            "--surface",
            scope.surface,
            "--version",
            scope.version,
            "--operation",
            scope.operation,
            "--route",
            scope.route,
        ]
    )
    try:
        grant = PrivateRouteQualificationGrant.model_validate(result.get("grant"))
    except Exception as exc:
        raise AcceptanceContractError(
            "qualification_grant_invalid", surface=scope.surface
        ) from exc
    if (
        grant.scope != scope
        or grant.sender_session_id != caller_session_id
        or grant.grant_digest != scope.digest
        or grant.project_id <= 0
        or not grant.operator_actor_id
        or grant.expired(now=datetime.now(timezone.utc))
    ):
        raise AcceptanceContractError(
            "qualification_grant_mismatch", surface=scope.surface
        )
    return OpenedQualification(grant=grant)


class QualificationCoordinator:
    """Open one grant at its operation boundary and verify it immediately."""

    def __init__(
        self,
        client: CommandClient,
        matrix: AcceptanceMatrix,
        *,
        run_id: str,
        release_sha: str,
        caller_session_id: str,
    ) -> None:
        self.client = client
        self.project = matrix.project
        self.run_id = run_id
        self.release_sha = release_sha
        self.caller_session_id = caller_session_id
        self._opened: list[OpenedQualification] = []
        self._verified: set[int] = set()
        self._lease_ids: set[int] = set()
        self._lease_keys: set[str] = set()

    def open(
        self,
        cell: AcceptanceCell,
        operation: str,
        route: str | None = None,
    ) -> OpenedQualification | None:
        if operation != acceptance_operation(cell.surface):
            return None
        if surface_operation_supported(cell.surface, cell.expected_version, operation):
            return None
        scope = PrivateRouteQualificationScope(
            release_sha=self.release_sha,
            acceptance_run_id=self.run_id,
            surface=cell.surface,
            version=cell.expected_version,
            operation=operation,
            route=_route(cell, operation, route),
        )
        if scope.lease_key in self._lease_keys:
            raise AcceptanceContractError(
                "qualification_scope_duplicate", surface=cell.surface
            )
        qualification = _open_one(
            self.client,
            project=self.project,
            caller_session_id=self.caller_session_id,
            scope=scope,
        )
        if qualification.grant.lease_id in self._lease_ids:
            raise AcceptanceContractError(
                "qualification_lease_duplicate", surface=cell.surface
            )
        self._lease_ids.add(qualification.grant.lease_id)
        self._lease_keys.add(scope.lease_key)
        self._opened.append(qualification)
        return qualification

    def verify(self, qualification: OpenedQualification | None) -> None:
        if qualification is None:
            return
        grant = qualification.grant
        result = self.client.call(
            [
                "coordination-claim",
                "list",
                "--project",
                self.project,
                "--key",
                grant.scope.lease_key,
            ]
        )
        leases = result.get("claims")
        if not isinstance(leases, list):
            raise AcceptanceContractError(
                "qualification_lease_missing", surface=grant.scope.surface
            )
        row: Any = next(
            (
                candidate
                for candidate in leases
                if isinstance(candidate, dict) and candidate.get("id") == grant.lease_id
            ),
            None,
        )
        if row is None:
            raise AcceptanceContractError(
                "qualification_lease_missing", surface=grant.scope.surface
            )
        if not isinstance(row, dict):
            raise AcceptanceContractError(
                "qualification_lease_invalid", surface=grant.scope.surface
            )
        # The holder identity IS the consumer identity: only the session
        # and actor the grant was opened for can consume it, so the claim's
        # own session_id / actor_id answer "who released this".
        if (
            row.get("id") != grant.lease_id
            or row.get("key") != grant.scope.lease_key
            or not row.get("released_at")
            or row.get("release_reason_intent") != QUALIFICATION_RELEASE_REASON
            or row.get("session_id") != grant.sender_session_id
            or str(row.get("actor_id") or "") != grant.operator_actor_id
        ):
            raise AcceptanceContractError(
                "qualification_not_consumed", surface=grant.scope.surface
            )
        self._verified.add(grant.lease_id)

    @property
    def all_consumed(self) -> bool:
        return self._verified == self._lease_ids

    def evidence(self) -> list[dict[str, object]]:
        """Expose stable, non-secret identifiers only."""
        return [
            {
                "lease_id": qualification.grant.lease_id,
                "grant_digest": qualification.grant.grant_digest,
            }
            for qualification in self._opened
        ]


__all__ = [
    "OpenedQualification",
    "QualificationCoordinator",
]
