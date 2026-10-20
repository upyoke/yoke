"""One strict contract for a displayed machine code and its verification URI."""

from dataclasses import dataclass
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from yoke_contracts.machine_authorization import MATCH_CODE_PATTERN


_ENTRY_PATHS = frozenset({"/connect", "/machine"})
# A self-host server on this machine's loopback serves plain HTTP.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_CODE_PATTERN = re.compile(MATCH_CODE_PATTERN)


@dataclass(frozen=True)
class MachineApprovalCoordinates:
    complete_uri: str
    origin: str
    user_code: str


def machine_approval_coordinates(
    uri: str, user_code: str
) -> MachineApprovalCoordinates:
    """Validate base and complete verification URIs without granting approval."""
    parsed = urlsplit(uri)
    code = user_code.strip().upper()
    if _CODE_PATTERN.fullmatch(code) is None:
        raise ValueError("machine approval code has an invalid shape")
    secure = parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS
    )
    if (
        not secure
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            "machine approval needs an HTTPS (or loopback HTTP) entry without "
            "credentials or a fragment"
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if parsed.path == f"/machine/{code}" and not parsed.query:
        return MachineApprovalCoordinates(uri, origin, code)
    if parsed.path not in _ENTRY_PATHS:
        raise ValueError("machine approval URL is not a supported entry path")
    if parsed.query:
        try:
            query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError:
            raise ValueError("machine approval query is malformed") from None
        if query != [("user_code", code)]:
            raise ValueError(
                "machine approval URL must contain only the displayed user_code"
            )
    complete = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode({"user_code": code}), "")
    )
    return MachineApprovalCoordinates(complete, origin, code)
