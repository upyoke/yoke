"""Single-use teammate invite values, code validation and replay refusal."""

import hashlib
import re
from dataclasses import dataclass, field

INVITE_TTL_SECONDS = 86400


class TeammateInviteError(ValueError):
    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


@dataclass(frozen=True)
class CreatedInvite:
    invite: dict
    code: str = field(repr=False)


def parse_invite_code(value: str) -> str:
    code = value.strip()
    if not re.fullmatch(r"yinv_[a-z2-7]{32}", code):
        raise TeammateInviteError(
            "invite_code_invalid",
            "enter the complete yinv_ code your inviter sent",
            404,
        )
    return code


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _replayed() -> TeammateInviteError:
    return TeammateInviteError(
        "result_unavailable",
        "this invite result was already issued; reissue the invite to receive a new code",
    )
