"""Device-code wire contract shared by Cloud, self-host, and their clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import urllib.parse
import re
from pydantic import BaseModel, ConfigDict, Field

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
RETRYABLE_POLL_ERRORS = {
    202: "authorization_pending",
    503: "machine_credential_unavailable",
}


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


def required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value or len(value) > 4096:
        raise HostedMachineAuthorizationError(f"hosted authorization omitted {key}")
    return value


def bounded_integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        ) from None
    if parsed < minimum or parsed > maximum:
        raise HostedMachineAuthorizationError(
            f"hosted authorization returned invalid {label}"
        )
    return parsed


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
