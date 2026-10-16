"""Private invite-code input and one-time machine credential delivery."""

import getpass
import json
import sys
import urllib.request
from collections.abc import Mapping

from pydantic import ValidationError

from yoke_cli.config import secrets
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    BoundedJsonHttpStatusError,
    request_json,
)
from yoke_contracts.machine_authorization import (
    HostedMachineAuthorizationCancelled,
    HostedMachineAuthorizationError,
    HostedMachineCredential,
    MachineAuthorizationApproved,
    authorization_origin,
    credential_api_url,
)
from yoke_contracts.teammate_invite_wire import INVITE_REDEEM_PATH, TeammateInviteRedeem

LOST_DELIVERY = (
    "Ask an admin to reissue the invite and retire any stray machine created "
    "by this attempt before connecting again."
)
_RECOVERY = {
    "invite_code_invalid": "Enter the complete code your inviter sent, or ask for a new one.",
    "invite_expired": "Ask your inviter to reissue the expired invite.",
    "invite_revoked": "Ask your inviter to reissue the revoked invite.",
    "invite_consumed": LOST_DELIVERY,
    "invite_actor_disabled": "Ask an org admin to enable the invited person, then retry.",
    "invite_machine_owned": "This machine belongs to another person; reconnect with a fresh machine UUID.",
    "machine_identity_required": "Restore this machine's configured UUID, name and platform, then retry.",
    "result_unavailable": LOST_DELIVERY,
    "invite_email_required": "This server uses company sign-in; ask for an email invite and sign in as yourself.",
    "invite_local_universe": "Set up a reachable team server with `yoke self-host init`.",
    "invite_reissue_disabled_actor": "Ask an org admin to enable the invited person before reissuing.",
    "oidc_misconfigured": "Ask the server operator to correct company sign-in settings, then retry.",
    "authorization_invite_redeem_rate_limited": "Too many attempts; wait for the server's Retry-After interval, then retry.",
    "authorization_store_unavailable": "Ask the server operator to restore the admission store, then retry.",
    "invite_store_unavailable": "Ask the server operator to check database health. "
    + LOST_DELIVERY,
    "machine_retired": "Ask an admin to inspect the retired registration and reconnect with a fresh machine UUID.",
}


def redeem(
    url: str, code: str, *, machine: Mapping[str, str]
) -> HostedMachineCredential:
    """Consume a code once; never replay a request whose delivery was lost."""
    origin = authorization_origin(url)
    try:
        model = TeammateInviteRedeem.model_validate({**machine, "invite_code": code})
    except ValidationError:
        raise HostedMachineAuthorizationError(
            "machine_identity_required: send the complete invite code and configured machine identity"
        ) from None
    request = urllib.request.Request(
        origin + INVITE_REDEEM_PATH,
        method="POST",
        data=json.dumps(model.model_dump()).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        result = request_json(
            request,
            timeout_seconds=15,
            replay_safe=False,
            allow_loopback_http=True,
            sensitive_values=(code,),
        )
    except BoundedJsonHttpStatusError as exc:
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        reason = payload.get("error")
        if not isinstance(reason, str) or reason not in _RECOVERY:
            reason = "invite_redemption_refused"
        recovery = _RECOVERY.get(
            reason, "Ask the server operator to inspect the refusal, then reconnect."
        )
        raise HostedMachineAuthorizationError(f"{reason}: {recovery}") from None
    except BoundedJsonHttpError:
        raise HostedMachineAuthorizationError(
            f"invite_delivery_unavailable: the connection ended without a usable credential. {LOST_DELIVERY}"
        ) from None
    try:
        response = MachineAuthorizationApproved.model_validate(result.payload)
        if result.status != 200 or any(
            secret in response.org for secret in (code, response.token)
        ):
            raise ValueError("invalid credential response")
    except (ValidationError, ValueError):
        raise HostedMachineAuthorizationError(
            f"invite_response_invalid: ask the operator to correct the response contract. {LOST_DELIVERY}"
        ) from None
    try:
        api_url = credential_api_url(
            response.api_url, origin, response.org, self_host=True
        )
    except (HostedMachineAuthorizationError, ValueError):
        raise HostedMachineAuthorizationError(
            f"invite_origin_mismatch: the credential names a different server. {LOST_DELIVERY}"
        ) from None
    return HostedMachineCredential(
        api_url=api_url, org=response.org, token=response.token
    )


def choose_code(*, from_stdin: bool = False, offer_choice: bool = False) -> str | None:
    """Return an invite code or own-machine choice; cancellation writes nothing."""
    try:
        if from_stdin:
            return secrets.read_stdin_secret("invite code")
        if not offer_choice or not sys.stdin.isatty():
            return None
        print("1) This is my own machine", file=sys.stderr)
        print(
            "2) Enter invite code (or ask an admin to run yoke invite <name> and send you the code)",
            file=sys.stderr,
        )
        print("3) Back", file=sys.stderr)
        while True:
            print("Choose [1/2/3]: ", end="", file=sys.stderr, flush=True)
            choice = input().strip()
            if choice == "1":
                return None
            if choice == "3":
                raise HostedMachineAuthorizationCancelled("connection cancelled")
            if choice == "2":
                code = getpass.getpass(
                    "Invite code (hidden; empty to go Back): "
                ).strip()
                if code:
                    return code
                raise HostedMachineAuthorizationCancelled("connection cancelled")
    except (EOFError, KeyboardInterrupt):
        raise HostedMachineAuthorizationCancelled("connection cancelled") from None
    except secrets.MachineSecretError:
        raise HostedMachineAuthorizationError(
            "invite_code_required: provide the invite code on stdin"
        ) from None
