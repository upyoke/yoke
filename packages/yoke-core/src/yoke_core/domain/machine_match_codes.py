"""Short, unambiguous match codes for pending machine connections."""

import secrets
from typing import Any

from yoke_core.domain.machine_authorization_codes import (
    MachineAuthorizationError,
    _p,
)

MATCH_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
MATCH_CODE_LENGTH = 4
MATCH_CODE_ATTEMPTS = 8


def generate_match_code() -> str:
    return "".join(
        secrets.choice(MATCH_CODE_ALPHABET) for _ in range(MATCH_CODE_LENGTH)
    )


def normalize_match_code(value: str) -> str:
    return value.strip().upper()


def allocate_match_code(conn: Any, *, attempts: int = MATCH_CODE_ATTEMPTS) -> str:
    """Allocate under start's transaction lock, before its matching insert."""
    p = _p(conn)
    for _ in range(attempts):
        code = generate_match_code()
        # Rows that expire after cleanup still reserve their unique code.
        if (
            conn.execute(
                f"SELECT 1 FROM machine_authorization_codes WHERE user_code={p}",
                (code,),
            ).fetchone()
            is None
        ):
            return code
    raise MachineAuthorizationError(
        "match_code_exhausted",
        "too many machines are connecting; retry in a minute",
        503,
    )
