"""The relay's identity gate: a poll must prove the machine id it claims.

Before the registry, a relay poll asserted its machine id and the control plane
believed it. A copied ``~/.yoke/config.json`` therefore made two hosts one
relay, and whichever polled took the other's wakes and launches. This gate is
the single place a poll is checked against the registered row, so every path
into the relay answers the same way.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.machine_identity import (
    MachineProofError,
    verify_machine_proof,
)
from yoke_core.domain.machine_registry import (
    MachineRecord,
    MachineRegistryError,
    canonical_machine_id,
    require_machine,
    touch_machine_seen,
)
from yoke_core.domain.session_relay_storage import utc_now


def require_proved_machine(
    conn: Any,
    *,
    machine_id: str,
    actor_id: int,
    proof_issued_at: str,
    proof_signature: str,
    now: str | None = None,
) -> MachineRecord:
    """Return the registered machine this poll proved, or refuse by name.

    Also stamps machine liveness, because a proved poll is the freshest
    evidence the control plane has that this host is up.
    """
    canonical = canonical_machine_id(machine_id)
    if not str(proof_issued_at).strip() or not str(proof_signature).strip():
        raise MachineRegistryError(
            "machine_proof_missing",
            f"relay poll for machine {canonical} carried no identity proof. "
            "Recovery: upgrade this machine's Yoke install and run "
            "`yoke machine register`, which mints the key the relay signs with.",
        )
    record = require_machine(conn, canonical)
    if int(record.owner_actor_id) != int(actor_id):
        raise MachineRegistryError(
            "machine_owner_mismatch",
            f"machine {canonical} is registered to another actor, so this relay "
            "may not poll as it. Recovery: clear this host's copied machine id "
            "and run `yoke machine register` to register it as its own machine.",
        )
    current = now or utc_now()
    try:
        verify_machine_proof(
            public_key=record.proof_public_key,
            machine_id=canonical,
            issued_at=str(proof_issued_at),
            signature=str(proof_signature),
            now=current,
        )
    except MachineProofError as exc:
        raise MachineRegistryError(exc.code, str(exc)) from exc
    touch_machine_seen(conn, machine_id=canonical, now=current)
    conn.commit()
    return record


__all__ = ["require_proved_machine"]
