"""Shared exact-origin validation for GitHub.com and GHES REST endpoints."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import urllib.parse

DEFAULT_GITHUB_API_URL = "https://api.github.com"
DEFAULT_GITHUB_WEB_URL = "https://github.com"
_REPOSITORY_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_APP_SLUG_SEGMENT = re.compile(r"^[A-Za-z0-9-]+$")
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

class GitHubApiOriginError(ValueError):
    """Raised when a GitHub API URL is not a safe exact HTTPS origin."""


@dataclass(frozen=True)
class GitHubEndpointPair:
    """Validated browser and API endpoints for one GitHub deployment."""

    api: "GitHubApiEndpoint"
    web: "GitHubWebEndpoint"
    deployment_kind: str

    def app_install_url(self, app_slug: str) -> str:
        if not isinstance(app_slug, str) or not _APP_SLUG_SEGMENT.fullmatch(app_slug):
            raise GitHubApiOriginError(
                "GitHub App slug may contain only letters, numbers, and hyphens"
            )
        segment = "github-apps" if self.deployment_kind == "ghes" else "apps"
        return self.web.url(f"/{segment}/{app_slug}/installations/new")

    def new_repository_url(self) -> str:
        """Configured deployment page for creating a repository manually."""
        return self.web.url("/new")

    def installation_settings_url(self, installation_id: int) -> str:
        """Configured deployment page for one installed GitHub App."""
        if (
            isinstance(installation_id, bool)
            or not isinstance(installation_id, int)
            or installation_id <= 0
        ):
            raise GitHubApiOriginError("GitHub App installation id must be a positive integer")
        return self.web.url(f"/settings/installations/{installation_id}")


@dataclass(frozen=True)
class GitHubApiEndpoint:
    """Validated GitHub REST base URL and its exact scheme/authority origin."""

    base_url: str
    origin: str

    def url(self, path: str) -> str:
        suffix = str(path or "").strip()
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"
        return f"{self.base_url}{suffix}"


@dataclass(frozen=True)
class GitHubWebEndpoint:
    """Validated GitHub browser base URL and exact HTTPS origin."""

    base_url: str
    origin: str

    def url(self, path: str) -> str:
        suffix = str(path or "").strip()
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"
        return f"{self.base_url}{suffix}"


def validate_github_api_endpoint(value: str | None) -> GitHubApiEndpoint:
    """Validate a configured GitHub.com or GHES REST base URL."""
    base_url, origin = _validate_https_endpoint(
        value, DEFAULT_GITHUB_API_URL, "GitHub API URL",
    )
    return GitHubApiEndpoint(base_url=base_url, origin=origin)


def validate_github_web_endpoint(value: str | None) -> GitHubWebEndpoint:
    """Validate a configured GitHub.com or GHES browser base URL."""
    base_url, origin = _validate_https_endpoint(
        value, DEFAULT_GITHUB_WEB_URL, "GitHub web URL",
    )
    return GitHubWebEndpoint(base_url=base_url, origin=origin)


def validate_github_endpoint_pair(
    api_url: str | None,
    web_url: str | None,
) -> GitHubEndpointPair:
    """Require browser authorization and API calls to target one deployment."""
    api = validate_github_api_endpoint(api_url)
    web = validate_github_web_endpoint(web_url)
    api_parts = urllib.parse.urlsplit(api.base_url)
    web_parts = urllib.parse.urlsplit(web.base_url)
    api_host = str(api_parts.hostname or "").lower()
    web_host = str(web_parts.hostname or "").lower()
    api_port = api_parts.port
    web_port = web_parts.port
    api_path = api_parts.path.rstrip("/")
    web_path = web_parts.path.rstrip("/")
    public_pair = (
        web_host == "github.com" and api_host == "api.github.com"
        and web_port is None and api_port is None
        and not web_path and not api_path
    )
    same_host_pair = (
        api_host == web_host
        and api_port == web_port
        and api_host not in {"github.com", "api.github.com"}
        and not web_path
        and api_path == "/api/v3"
    )
    data_residency_pair = (
        web_host.endswith(".ghe.com")
        and api_host == f"api.{web_host}"
        and api_port == web_port
        and not web_path
        and not api_path
    )
    if not (public_pair or same_host_pair or data_residency_pair):
        raise GitHubApiOriginError(
            "GitHub API URL and web URL must use canonical bases for the same "
            "deployment (GitHub Cloud origins are pathless; GitHub Enterprise "
            "Server uses a pathless web origin and /api/v3 API base)"
        )
    deployment_kind = (
        "github_cloud" if public_pair
        else "data_residency" if data_residency_pair
        else "ghes"
    )
    return GitHubEndpointPair(
        api=api, web=web, deployment_kind=deployment_kind,
    )


def github_web_url_from_api(api_url: str) -> str:
    """Return the canonical browser base paired with a GitHub API base."""
    endpoint = validate_github_api_endpoint(api_url)
    parsed = urllib.parse.urlsplit(endpoint.base_url)
    hostname = str(parsed.hostname or "")
    if endpoint.base_url == DEFAULT_GITHUB_API_URL:
        web_url = DEFAULT_GITHUB_WEB_URL
    elif hostname.startswith("api.") and hostname.endswith(".ghe.com"):
        authority = hostname.removeprefix("api.")
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        web_url = f"https://{authority}"
    elif parsed.path.rstrip("/") == "/api/v3":
        web_url = endpoint.origin
    else:
        raise GitHubApiOriginError(
            "GitHub API URL must be a canonical GitHub Cloud, GitHub "
            "Enterprise Cloud data-residency, or GHES base"
        )
    return validate_github_endpoint_pair(api_url, web_url).web.base_url


def _validate_https_endpoint(
    value: str | None,
    default: str,
    label: str,
) -> tuple[str, str]:
    candidate = str(value or default)
    if any(
        char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F
        for char in candidate
    ):
        raise GitHubApiOriginError(
            f"{label} must not contain whitespace or control characters"
        )
    raw = candidate.rstrip("/")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise GitHubApiOriginError(f"{label} is malformed") from exc
    if parsed.scheme.lower() != "https":
        raise GitHubApiOriginError(f"{label} must use https")
    if not parsed.hostname:
        raise GitHubApiOriginError(f"{label} must include a hostname")
    if parsed.username or parsed.password:
        raise GitHubApiOriginError(f"{label} must not include credentials")
    if parsed.query or parsed.fragment:
        raise GitHubApiOriginError(
            f"{label} must not include a query string or fragment"
        )
    decoded_path = urllib.parse.unquote(parsed.path)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded_path):
        raise GitHubApiOriginError(
            f"{label} path must not contain encoded control characters"
        )
    if "\\" in decoded_path or any(
        part in {".", ".."} for part in decoded_path.split("/")
    ):
        raise GitHubApiOriginError(f"{label} path must not contain dot segments")
    try:
        port = parsed.port
    except ValueError as exc:
        raise GitHubApiOriginError(f"{label} port is invalid") from exc
    host = _validated_hostname(parsed.hostname, label=label)
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    origin = f"https://{authority}"
    path = parsed.path.rstrip("/")
    return f"{origin}{path}", origin


def _validated_hostname(value: str, *, label: str) -> str:
    host = value.casefold()
    try:
        parsed_ip = ipaddress.ip_address(host)
    except ValueError:
        if ":" in host or re.fullmatch(r"[0-9.]+", host):
            raise GitHubApiOriginError(f"{label} hostname is invalid")
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise GitHubApiOriginError(f"{label} hostname is invalid") from exc
        labels = ascii_host.split(".")
        if (
            len(ascii_host) > 253
            or any(not _DNS_LABEL.fullmatch(part) for part in labels)
        ):
            raise GitHubApiOriginError(f"{label} hostname is invalid")
        return ascii_host
    return parsed_ip.compressed


def require_same_github_origin(url: str, endpoint: GitHubApiEndpoint) -> None:
    """Reject absolute request or redirect URLs outside ``endpoint``."""
    raw_url = str(url or "")
    if any(char.isspace() or ord(char) < 0x20 for char in raw_url):
        raise GitHubApiOriginError("GitHub request URL contains unsafe whitespace")
    parsed = urllib.parse.urlsplit(raw_url)
    if not parsed.scheme or not parsed.netloc:
        raise GitHubApiOriginError("GitHub request URL must be absolute")
    candidate = validate_github_api_endpoint(
        urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    )
    if candidate.origin != endpoint.origin:
        raise GitHubApiOriginError(
            "GitHub request or redirect crossed the configured API origin"
        )
    base_path = urllib.parse.unquote(
        urllib.parse.urlsplit(endpoint.base_url).path).rstrip("/")
    request_path = urllib.parse.unquote(parsed.path)
    encoded_path = parsed.path.casefold()
    if any(marker in encoded_path for marker in ("%2e", "%2f", "%5c")):
        raise GitHubApiOriginError(
            "GitHub request path must not encode separators or dot segments"
        )
    if "\\" in request_path or any(
        part in {".", ".."} for part in request_path.split("/")
    ):
        raise GitHubApiOriginError(
            "GitHub request path must not contain dot segments or backslashes"
        )
    allowed_graphql = base_path == "/api/v3" and request_path == "/api/graphql"
    if base_path and not (allowed_graphql or request_path == base_path
                          or request_path.startswith(f"{base_path}/")):
        raise GitHubApiOriginError(
            "GitHub request or redirect left the configured API base path"
        )


def normalize_github_repository(
    value: str,
    *,
    web_url: str | None = None,
) -> str:
    """Return ``owner/repo`` from a bare, HTTPS, or scp-style GitHub reference.

    Supplying ``web_url`` requires an exact configured GitHub deployment origin;
    callers that only normalize metadata may omit it to accept a host-agnostic
    GHES reference without authorizing any network request.
    """
    raw = str(value or "").strip()
    if not raw:
        raise GitHubApiOriginError("GitHub repository reference is required")
    endpoint = validate_github_web_endpoint(web_url) if web_url else None
    scp = re.fullmatch(r"git@([^:/\\]+):(.+)", raw)
    if scp:
        if endpoint and scp.group(1).casefold() != _endpoint_host(endpoint):
            raise GitHubApiOriginError(
                "GitHub repository SSH host does not match the configured web URL"
            )
        path = scp.group(2)
    elif "://" in raw:
        parsed = urllib.parse.urlsplit(raw)
        scheme = parsed.scheme.lower()
        if scheme not in {"https", "ssh"} or not parsed.hostname:
            raise GitHubApiOriginError(
                "GitHub repository URL must use https or ssh"
            )
        invalid_user = (
            parsed.username is not None
            if scheme == "https"
            else parsed.username not in {None, "git"}
        )
        if invalid_user or parsed.password or parsed.query or parsed.fragment:
            raise GitHubApiOriginError(
                "GitHub repository URL must not include credentials, query, or fragment"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise GitHubApiOriginError(
                "GitHub repository URL port is invalid"
            ) from exc
        if scheme == "ssh" and port not in (None, 22):
            raise GitHubApiOriginError("GitHub repository SSH URL must use port 22")
        if scheme == "https":
            candidate = validate_github_web_endpoint(
                urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            )
            if endpoint and candidate.origin != endpoint.origin:
                raise GitHubApiOriginError(
                    "GitHub repository URL does not match the configured web origin"
                )
        elif endpoint and parsed.hostname.casefold() != _endpoint_host(endpoint):
            raise GitHubApiOriginError(
                "GitHub repository SSH host does not match the configured web URL"
            )
        path = urllib.parse.unquote(parsed.path)
        if endpoint and scheme == "https":
            base_path = urllib.parse.urlsplit(endpoint.base_url).path.rstrip("/")
            if base_path and not path.startswith(f"{base_path}/"):
                raise GitHubApiOriginError(
                    "GitHub repository URL is outside the configured web base path"
                )
            path = path[len(base_path):]
    else:
        if any(marker in raw for marker in ("@", ":", "\\")):
            raise GitHubApiOriginError("GitHub repository reference is malformed")
        path = raw
    cleaned = path.strip("/").removesuffix(".git")
    parts = cleaned.split("/")
    if len(parts) != 2 or not all(_REPOSITORY_SEGMENT.fullmatch(part) for part in parts):
        raise GitHubApiOriginError(
            "GitHub repository reference must contain exactly owner/repo"
        )
    if any(part in {".", ".."} for part in parts):
        raise GitHubApiOriginError("GitHub repository path must not contain dot segments")
    return f"{parts[0]}/{parts[1]}"


def _endpoint_host(endpoint: GitHubWebEndpoint) -> str:
    return str(urllib.parse.urlsplit(endpoint.origin).hostname or "").casefold()


__all__ = [
    "DEFAULT_GITHUB_API_URL",
    "DEFAULT_GITHUB_WEB_URL",
    "GitHubApiEndpoint",
    "GitHubApiOriginError",
    "GitHubEndpointPair",
    "GitHubWebEndpoint",
    "github_web_url_from_api",
    "require_same_github_origin",
    "normalize_github_repository",
    "validate_github_api_endpoint",
    "validate_github_endpoint_pair",
    "validate_github_web_endpoint",
]
