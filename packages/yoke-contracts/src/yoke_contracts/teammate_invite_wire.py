"""Single-use teammate invite redemption, separate from device authorization."""

from pydantic import Field

from yoke_contracts.machine_authorization import MachineAuthorizationIdentity, WireText

INVITE_REDEEM_PATH = "/api/machine/authorizations/invite"
INVITE_CODE_PREFIX = "yinv_"


class TeammateInviteRedeem(MachineAuthorizationIdentity):
    platform: str = Field(min_length=1, max_length=80)
    invite_code: WireText = Field(repr=False)
