"""Device-code wire contract shared by Cloud, self-host, and their clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal
import urllib.parse
import re
from pydantic import BaseModel, ConfigDict, Field, ValidationError

START_PATH = "/api/machine/authorizations"
POLL_PATH = START_PATH + "/token"
APPROVAL_PAGE_PATH = "/machine-approval"
CODE_TTL_SECONDS = 600
POLL_INTERVAL_SECONDS = 2
APPROVAL_RETURN_COOKIE = "yoke_machine_approval_return"


class HostedMachineAuthorizationError(RuntimeError):
    """The hosted browser authorization could not complete safely."""


class HostedMachineAuthorizationDenied(HostedMachineAuthorizationError):
    """The user explicitly denied this machine in the browser."""


class HostedMachineAuthorizationCancelled(HostedMachineAuthorizationError):
    """The caller abandoned the approval wait; the pending code simply expires."""


# Hosted pages that may present the one-time code approval: the dedicated
# machine-approval page and the unified connect-machine page.
BROWSER_VERIFICATION_PATHS = ("/connect", "/machine", APPROVAL_PAGE_PATH)


@dataclass(frozen=True)
class PendingMachineAuthorization:
    platform_url: str
    device_code: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int
    self_host: bool = False


@dataclass(frozen=True)
class HostedMachineCredential:
    api_url: str
    org: str
    token: str = field(repr=False)


def authorization_origin(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip().rstrip("/"))
        parsed.port
    except ValueError:
        raise HostedMachineAuthorizationError(
            "authorization_origin_invalid: enter a valid server origin"
        ) from None
    if (
        not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"})
        )
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise HostedMachineAuthorizationError(
            "authorization_origin_invalid: use HTTPS, or numeric loopback HTTP for a local server"
        )
    if parsed.path or parsed.query or parsed.fragment:
        raise HostedMachineAuthorizationError(
            "authorization_origin_invalid: use the server origin without a path"
        )
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def same_origin_url(value: str, origin: str, *, expected_paths: tuple[str, ...]) -> str:
    parsed = urllib.parse.urlsplit(value)
    expected = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
        or (parsed.path not in expected_paths and not approval_return_path(parsed.path))
        or parsed.fragment
    ):
        raise HostedMachineAuthorizationError(
            "hosted authorization returned an unsafe browser URL"
        )
    return value


def credential_api_url(
    value: str, origin: str, org: str, *, self_host: bool = False
) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    expected = urllib.parse.urlsplit(origin)
    if (
        parsed.scheme != expected.scheme
        or parsed.netloc != expected.netloc
        or parsed.path
        != ("" if self_host else f"/api/orgs/{urllib.parse.quote(org, safe='')}")
        or parsed.query
        or parsed.fragment
    ):
        raise HostedMachineAuthorizationError(
            "authorization_authority_invalid: server returned an unsafe or mismatched API authority; restart connection with the intended server"
        )
    return value.rstrip("/")


class MachineAuthorizationStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str = Field(min_length=1, max_length=100)
    machine_name: str = Field(min_length=1, max_length=150)


class MachineAuthorizationPoll(MachineAuthorizationStart):
    device_code: str = Field(min_length=1, max_length=4096, repr=False)


def approval_return_path(value: str) -> str:
    """Only an approval page can be retained through company sign-in."""
    return (
        value
        if re.fullmatch(
            re.escape(APPROVAL_PAGE_PATH) + r"(?:/[A-Za-z0-9-]{1,32})?", value
        )
        else ""
    )


WireText = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")]


class MachineAuthorizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MachineAuthorizationStarted(MachineAuthorizationResponse):
    device_code: WireText = Field(repr=False)
    user_code: WireText
    verification_uri: WireText
    verification_uri_complete: WireText
    expires_in: int = Field(ge=60, le=1800)
    interval: int = Field(ge=1, le=30)


class MachineAuthorizationApproved(MachineAuthorizationResponse):
    token: WireText = Field(repr=False)
    org: WireText
    api_url: WireText


class MachineAuthorizationRefused(MachineAuthorizationResponse):
    error: WireText
    # Cloud may omit recovery text; self-host always supplies it.
    message: WireText | None = None


class MachineAuthorizationPending(MachineAuthorizationRefused):
    error: Literal["authorization_pending"]


class MachineAuthorizationDenied(MachineAuthorizationRefused):
    error: Literal["authorization_denied"]


class MachineAuthorizationExpired(MachineAuthorizationRefused):
    error: Literal["authorization_expired", "authorization_consumed"]


class MachineAuthorizationSlowDown(MachineAuthorizationRefused):
    error: Literal["authorization_poll_rate_limited"]


class MachineAuthorizationUnavailable(MachineAuthorizationRefused):
    error: Literal["machine_credential_unavailable"]


# HTTP status is part of the contract, independently of the JSON body.
POLL_OUTCOMES = {
    "authorization_pending": (202, MachineAuthorizationPending),
    "authorization_denied": (410, MachineAuthorizationDenied),
    "authorization_expired": (410, MachineAuthorizationExpired),
    "authorization_consumed": (410, MachineAuthorizationExpired),
    "authorization_poll_rate_limited": (429, MachineAuthorizationSlowDown),
    "machine_credential_unavailable": (503, MachineAuthorizationUnavailable),
}

RETRYABLE_POLL_ERRORS = {
    status: error
    for error, (status, model) in POLL_OUTCOMES.items()
    if model in {MachineAuthorizationPending, MachineAuthorizationUnavailable}
}


def parse_authorization_response(
    payload: object, status: int, *, operation: Literal["start", "poll"]
) -> MachineAuthorizationResponse:
    """Parse wire bodies without leaking device secrets or credentials on failure."""
    model = (
        MachineAuthorizationStarted
        if operation == "start"
        else MachineAuthorizationApproved
    )
    if status != 200:
        model = MachineAuthorizationRefused
        error = payload.get("error") if isinstance(payload, dict) else None
        if operation == "poll" and isinstance(error, str) and error in POLL_OUTCOMES:
            expected_status, model = POLL_OUTCOMES[error]
            if status != expected_status:
                raise HostedMachineAuthorizationError(
                    "authorization_response_invalid: polling failed "
                    f"(HTTP {status}); correct the server's machine sign-in contract, then reconnect"
                )
        elif status not in {400, 403, 409, 410, 429, 503}:
            raise HostedMachineAuthorizationError(
                f"authorization_response_invalid: {operation} polling failed (HTTP {status}); "
                "correct the server's machine sign-in contract, then reconnect"
            )
    try:
        return model.model_validate(payload)
    except ValidationError:
        raise HostedMachineAuthorizationError(
            f"authorization_response_invalid: {operation} polling failed (HTTP {status}); "
            "correct the server's machine sign-in response schema, then reconnect"
        ) from None
