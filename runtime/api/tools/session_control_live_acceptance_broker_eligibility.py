"""One broker-session eligibility contract for preview and registration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
)
from yoke_contracts.session_control.surface_versions import surface_version_meets_floor
from yoke_cli.commands.adapters.session_control_acceptance import PREPARE_BROKER_FLAG


#: Candidates existed on the named machine and none of them, in either role,
#: satisfied every declared axis.
NO_CLAIM_FREE_PAIR_CODE = "no_claim_free_broker_pair"

#: The roster named no session at all for the decision to weigh. A different
#: fact from "every candidate was refused", and it wants the same next action
#: for a different reason, so the operator is told which one they hit.
NO_BROKER_CANDIDATES_CODE = "no_broker_candidates"

#: Preparation launched a dedicated pair, the pair registered, and by the
#: re-read the sessions were gone. Never reported as a shortage of candidates:
#: the pair existed and did not survive.
PREPARED_SESSIONS_ENDED_CODE = "prepared_broker_sessions_ended"

_PREPARE_RECOVERY = (
    f"Rerun preview with {PREPARE_BROKER_FLAG} to launch two dedicated claim-free "
    "codex-cli sessions on the selected machine, wait for registration, and "
    "re-preview."
)
NO_CLAIM_FREE_PAIR_RECOVERY = (
    "Every session considered failed at least one declared axis; the preview's "
    "considered_sessions names which axis each failed for each role. "
    + _PREPARE_RECOVERY
)
NO_BROKER_CANDIDATES_RECOVERY = (
    "No session was considered at all on the selected machine. Confirm the "
    "machine has a live relay for the surface, then: " + _PREPARE_RECOVERY
)


def prepared_sessions_ended_recovery(session_ids: Sequence[str]) -> str:
    """Say which prepared sessions died, and how to keep the next pair alive."""
    named = ", ".join(session_ids) or "the prepared pair"
    return (
        f"Preparation registered {named} and the sessions were gone by the "
        "re-read, so preparation refuses rather than reporting a shortage of "
        "candidates. A broker session holds no work claim by design, so idle "
        "cleanup ends it the moment its turn stops unless something holds it: "
        "preparation takes that hold itself, so this means the hold did not "
        "land. Check `yoke sessions keepalive hold <session-id> --reason ...` "
        "against one of those ids for the refusal it reports, then rerun "
        f"preview with {PREPARE_BROKER_FLAG}."
    )


BrokerRole = Literal["target", "peer"]


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
    considered: tuple[dict[str, Any], ...] = ()


def _role_code(role: BrokerRole, target: str, peer: str) -> str:
    return target if role == "target" else peer


def broker_session_eligibility(
    row: Mapping[str, Any] | None,
    *,
    project: str,
    surface: str,
    advertised_version: str,
    machine_id: str,
    role: BrokerRole,
    allow_ended: bool = False,
) -> str | None:
    """Return the registration failure code, or ``None`` when eligible.

    Preview passes ``allow_ended=False`` and registration passes its actual
    baseline allowance. Therefore every preview-ready row is accepted by the
    same registration predicate while wakeable rows that end after preview can
    still satisfy the runner's explicit ended-baseline contract.
    """
    if row is None:
        return _role_code(role, "registration_missing", "broker_registration_missing")
    if row.get("project") != project:
        return _role_code(
            role, "registration_project_mismatch", "broker_project_mismatch"
        )
    if row.get("executor_surface") != surface:
        return _role_code(
            role, "registration_surface_mismatch", "broker_surface_mismatch"
        )
    registered = str(row.get("executor_version") or "")
    if not surface_version_meets_floor(surface, registered, advertised_version):
        return _role_code(
            role, "registration_version_mismatch", "broker_version_mismatch"
        )
    if row.get("machine_id") != machine_id:
        return _role_code(
            role, "registration_machine_mismatch", "broker_machine_mismatch"
        )
    mode = row.get("mode")
    if not isinstance(mode, str) or not mode.strip():
        return "registration_mode_missing"
    if row.get("claims") != []:
        return "registration_claims_present"
    if "current_item" not in row or row.get("current_item") is not None:
        return "registration_item_present"
    liveness = row.get("liveness")
    active = liveness == "active" and not row.get("terminated_at")
    if not active and not (allow_ended and liveness == "ended"):
        return _role_code(role, "registration_not_active", "broker_not_active")
    if role == "peer" and active:
        routing = row.get("messageability")
        if not isinstance(routing, dict) or routing.get("hook_injection") is not True:
            return "broker_hook_route_missing"
    return None


def require_broker_session_eligibility(
    row: Mapping[str, Any],
    *,
    project: str,
    surface: str,
    advertised_version: str,
    machine_id: str,
    role: BrokerRole,
    allow_ended: bool,
) -> None:
    code = broker_session_eligibility(
        row,
        project=project,
        surface=surface,
        advertised_version=advertised_version,
        machine_id=machine_id,
        role=role,
        allow_ended=allow_ended,
    )
    if code is not None:
        raise AcceptanceContractError(code, surface=surface)


def _session_id(row: Mapping[str, Any] | None) -> str:
    return str((row or {}).get("session_id") or "").strip()


def _eligible(
    row: Mapping[str, Any] | None,
    *,
    project: str,
    surface: str,
    advertised_version: str,
    machine_id: str,
    role: BrokerRole,
) -> bool:
    return (
        broker_session_eligibility(
            row,
            project=project,
            surface=surface,
            advertised_version=advertised_version,
            machine_id=machine_id,
            role=role,
        )
        is None
    )


def _pick_unused(
    candidates: Sequence[Mapping[str, Any]], used: set[str]
) -> Mapping[str, Any] | None:
    for row in candidates:
        session_id = _session_id(row)
        if session_id and session_id not in used:
            return row
    return None


def select_broker_binding(
    binding: BrokerBinding,
    *,
    project: str,
    surface: str,
    advertised_version: str,
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]],
) -> BrokerBinding | None:
    """Select two claim-free rows registration accepts on the named machine."""
    eligible = {
        role: sorted(
            (
                row
                for row in candidates
                if _eligible(
                    row,
                    project=project,
                    surface=surface,
                    advertised_version=advertised_version,
                    machine_id=binding.machine_id,
                    role=role,
                )
            ),
            key=_session_id,
        )
        for role in ("target", "peer")
    }
    selected_target = (
        target
        if _eligible(
            target,
            project=project,
            surface=surface,
            advertised_version=advertised_version,
            machine_id=binding.machine_id,
            role="target",
        )
        else None
    )
    selected_peer = (
        peer
        if _eligible(
            peer,
            project=project,
            surface=surface,
            advertised_version=advertised_version,
            machine_id=binding.machine_id,
            role="peer",
        )
        else None
    )
    used = {_session_id(selected_target), _session_id(selected_peer)} - {""}
    if selected_target is None:
        selected_target = _pick_unused(eligible["target"], used)
        if selected_target is None:
            return None
        used.add(_session_id(selected_target))
    if selected_peer is None:
        selected_peer = _pick_unused(eligible["peer"], used)
        if selected_peer is None:
            return None
    target_id = _session_id(selected_target)
    peer_id = _session_id(selected_peer)
    if not target_id or not peer_id or target_id == peer_id:
        return None
    return BrokerBinding(target_id, binding.machine_id, peer_id)


def decide_broker_binding(
    binding: BrokerBinding,
    *,
    project: str,
    surface: str,
    advertised_version: str,
    target: Mapping[str, Any] | None,
    peer: Mapping[str, Any] | None,
    candidates: Sequence[Mapping[str, Any]] = (),
) -> BrokerBindingDecision:
    from runtime.api.tools.session_control_live_acceptance_broker_candidates import (
        candidate_evidence,
    )

    considered = candidate_evidence(
        binding,
        project=project,
        surface=surface,
        advertised_version=advertised_version,
        target=target,
        peer=peer,
        candidates=candidates,
    )
    selected = select_broker_binding(
        binding,
        project=project,
        surface=surface,
        advertised_version=advertised_version,
        target=target,
        peer=peer,
        candidates=candidates,
    )
    if selected is not None:
        return BrokerBindingDecision(
            "ready",
            selected,
            advertised_version=advertised_version,
            considered=considered,
        )
    empty = not considered
    return BrokerBindingDecision(
        "not_ready",
        binding,
        failure_code=(
            NO_BROKER_CANDIDATES_CODE if empty else NO_CLAIM_FREE_PAIR_CODE
        ),
        recovery=(
            NO_BROKER_CANDIDATES_RECOVERY if empty else NO_CLAIM_FREE_PAIR_RECOVERY
        ),
        advertised_version=advertised_version,
        considered=considered,
    )


__all__ = [
    "NO_BROKER_CANDIDATES_CODE",
    "NO_BROKER_CANDIDATES_RECOVERY",
    "NO_CLAIM_FREE_PAIR_CODE",
    "NO_CLAIM_FREE_PAIR_RECOVERY",
    "PREPARED_SESSIONS_ENDED_CODE",
    "BrokerBinding",
    "BrokerBindingDecision",
    "BrokerRole",
    "broker_session_eligibility",
    "decide_broker_binding",
    "require_broker_session_eligibility",
    "prepared_sessions_ended_recovery",
    "select_broker_binding",
]
