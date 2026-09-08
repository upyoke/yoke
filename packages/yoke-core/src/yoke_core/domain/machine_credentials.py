"""Atomic machine registration, credential rotation, and retirement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.api_tokens import generate_token, hash_token
from yoke_core.domain.machine_registry import (
    MachineRecord,
    marker,
    register_machine,
    retire_machine,
)


@dataclass(frozen=True)
class MachineCredential:
    token_id: int
    token: str
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "token": self.token,
            "status": self.status,
            "created_at": self.created_at,
        }


def _audit(
    conn: Any,
    *,
    token_id: int,
    actor_id: int,
    event_type: str,
    outcome: str,
    now: str,
) -> None:
    p = marker(conn)
    conn.execute(
        "INSERT INTO api_token_audit "
        "(api_token_id,actor_id,event_type,outcome,created_at) "
        f"VALUES ({p},{p},{p},{p},{p})",
        (token_id, actor_id, event_type, outcome, now),
    )


def _revoke_active(conn: Any, *, machine_id: str, actor_id: int, now: str) -> None:
    p = marker(conn)
    rows = conn.execute(
        f"SELECT id FROM api_tokens WHERE machine_id={p} AND status='active'",
        (machine_id,),
    ).fetchall()
    for row in rows:
        token_id = int(row[0])
        conn.execute(
            f"UPDATE api_tokens SET status='revoked',revoked_at={p} WHERE id={p}",
            (now, token_id),
        )
        _audit(
            conn,
            token_id=token_id,
            actor_id=actor_id,
            event_type="revoked",
            outcome="machine_rotation",
            now=now,
        )


def register_with_credential(
    conn: Any,
    *,
    machine_id: str,
    name: str,
    actor_id: int,
    access: Any = None,
    is_admin: bool = False,
    now: str,
) -> tuple[MachineRecord, bool, MachineCredential]:
    """Register a machine and return its new raw bearer exactly once."""
    try:
        record, created = register_machine(
            conn,
            machine_id=machine_id,
            name=name,
            actor_id=actor_id,
            access=access,
            is_admin=is_admin,
            now=now,
            commit=False,
        )
        _revoke_active(
            conn,
            machine_id=record.machine_id,
            actor_id=actor_id,
            now=now,
        )
        raw = generate_token()
        p = marker(conn)
        row = conn.execute(
            "INSERT INTO api_tokens "
            "(token_hash,actor_id,machine_id,name,status,created_at) "
            f"VALUES ({p},{p},{p},{p},'active',{p}) RETURNING id",
            (
                hash_token(raw),
                record.owner_actor_id,
                record.machine_id,
                f"machine:{record.machine_id}",
                now,
            ),
        ).fetchone()
        credential = MachineCredential(
            token_id=int(row[0]), token=raw, status="active", created_at=now
        )
        _audit(
            conn,
            token_id=credential.token_id,
            actor_id=record.owner_actor_id,
            event_type="issued",
            outcome="success",
            now=now,
        )
        conn.commit()
        return record, created, credential
    except Exception:
        conn.rollback()
        raise


def retire_with_credentials(
    conn: Any,
    *,
    machine_id: str,
    actor_id: int,
    is_admin: bool = False,
    now: str,
) -> MachineRecord:
    """Retire a machine and revoke only credentials bound to it."""
    try:
        record = retire_machine(
            conn,
            machine_id=machine_id,
            actor_id=actor_id,
            is_admin=is_admin,
            now=now,
            commit=False,
        )
        _revoke_active(
            conn,
            machine_id=record.machine_id,
            actor_id=actor_id,
            now=now,
        )
        conn.commit()
        return record
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "MachineCredential",
    "register_with_credential",
    "retire_with_credentials",
]
