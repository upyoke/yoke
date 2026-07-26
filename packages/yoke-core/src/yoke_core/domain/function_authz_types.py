"""Authorization scope names and immutable classification result."""

from dataclasses import dataclass


PROJECT = "project"
ORG = "org"
CONTROL_PLANE = "control_plane"
ACTOR_SESSION = "actor_session"
CLIENT_LOCAL = "client_local"
DENY = "deny"


@dataclass(frozen=True)
class AuthzSpec:
    """How to authorize one function call."""

    scope: str
    permission_key: str | None


__all__ = [
    "ACTOR_SESSION",
    "AuthzSpec",
    "CLIENT_LOCAL",
    "CONTROL_PLANE",
    "DENY",
    "ORG",
    "PROJECT",
]
