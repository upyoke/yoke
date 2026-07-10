"""Atomic, refresh-aware storage for local GitHub App user credentials."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
import urllib.error
import urllib.parse
import urllib.request

try:
    from yoke_contracts import github_origin
except ModuleNotFoundError:  # pragma: no cover - copied source-dev helper
    import _yoke_github_origin as github_origin  # type: ignore
try:
    from yoke_contracts import github_app_tokens as token_contract
except ModuleNotFoundError:  # pragma: no cover - copied source-dev helper
    import _yoke_github_app_tokens as token_contract  # type: ignore
try:
    from yoke_cli.config import github_git_credential_file as credential_file
except Exception:  # pragma: no cover - copied source-dev helper
    import _yoke_github_git_credential_file as credential_file  # type: ignore

CREDENTIAL_SCHEMA_VERSION = 1
DEFAULT_GITHUB_WEB_URL = github_origin.DEFAULT_GITHUB_WEB_URL
TOKEN_CACHE_SKEW_SECONDS = 60


class GitHubCredentialStoreError(RuntimeError):
    """The local GitHub App credential cannot provide an access token."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def access_token_from_machine_config(
    config_path: str | Path | None,
    *,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    client_secret: str | None = None,
) -> dict[str, Any]:
    return access_token_from_config(
        load_config(config_path), opener=opener, now=now,
        timeout_seconds=timeout_seconds, client_secret=client_secret,
    )


def access_token_from_config(
    config: Mapping[str, Any],
    *,
    opener: Callable[..., Any] | None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    client_secret: str | None = None,
) -> dict[str, Any]:
    github = config.get("github")
    if not isinstance(github, Mapping):
        raise GitHubCredentialStoreError(
            "machine GitHub App authorization is not configured"
        )
    client_id = _required_string(github.get("client_id"), "github.client_id")
    authorization = github.get("authorization")
    if not isinstance(authorization, Mapping):
        raise GitHubCredentialStoreError("github.authorization must be an object")
    if authorization.get("kind") != token_contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION:
        raise GitHubCredentialStoreError(
            "github.authorization.kind must match the GitHub App user authorization kind"
        )
    auth_status = str(authorization.get("status") or "")
    if auth_status != "authorized":
        raise GitHubCredentialStoreError(
            f"GitHub App user authorization is not authorized: "
            f"{auth_status or '<missing>'}"
        )
    try:
        endpoint_pair = github_origin.validate_github_endpoint_pair(
            str(github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(github.get("web_url") or DEFAULT_GITHUB_WEB_URL),
        )
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc
    path = Path(_required_string(
        authorization.get("refresh_credential_ref"),
        "github.authorization.refresh_credential_ref",
    )).expanduser()
    selected_now = _ensure_utc(now or datetime.now(timezone.utc))
    with _locked(path):
        current = read_credential_document(path)
        expires_at = _parse_timestamp(current.get("expires_at"), "expires_at")
        if expires_at > selected_now + timedelta(seconds=TOKEN_CACHE_SKEW_SECONDS):
            return _result(current, path=path, cached=True, rotated=False)
        refresh_expires_at = _parse_timestamp(
            current.get("refresh_expires_at"), "refresh_expires_at"
        )
        if refresh_expires_at <= selected_now:
            raise GitHubCredentialStoreError(
                "GitHub App refresh credential expired; run `yoke github connect` "
                "to authorize again"
            )
        refreshed = refresh_credential_document(
            client_id=client_id,
            refresh_token=_required_string(
                current.get("refresh_token"), "refresh_token"
            ),
            login_base=endpoint_pair.web.base_url,
            opener=opener,
            now=selected_now,
            timeout_seconds=timeout_seconds,
            client_secret=client_secret,
        )
        rotated = refreshed["refresh_token"] != current.get("refresh_token")
        try:
            write_credential_document(path, refreshed)
        except GitHubCredentialStoreError as exc:
            raise GitHubCredentialStoreError(
                "GitHub rotated the user credential but its local save failed; "
                "run `yoke github connect` to recover"
            ) from exc
        return _result(refreshed, path=path, cached=False, rotated=rotated)


def credential_document_from_token_response(
    payload: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = _ensure_utc(now or datetime.now(timezone.utc))
    try:
        return {
            "schema_version": CREDENTIAL_SCHEMA_VERSION,
            "access_token": _required_string(
                payload.get("access_token"), "access_token"
            ),
            "expires_at": _expiry_timestamp(
                payload.get("expires_in"), now=selected_now, label="expires_in"
            ).isoformat(),
            "refresh_token": _required_string(
                payload.get("refresh_token"), "refresh_token"
            ),
            "refresh_expires_at": _expiry_timestamp(
                payload.get("refresh_token_expires_in"), now=selected_now,
                label="refresh_token_expires_in",
            ).isoformat(),
            "scope": str(payload.get("scope") or ""),
            "token_type": str(payload.get("token_type") or "bearer"),
        }
    except GitHubCredentialStoreError as exc:
        raise GitHubCredentialStoreError(
            f"{exc}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc


def refresh_credential_document(
    *, client_id: str, refresh_token: str,
    login_base: str = DEFAULT_GITHUB_WEB_URL,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    client_secret: str | None = None,
) -> dict[str, Any]:
    params = {
        "client_id": _required_string(client_id, "client_id"),
        "grant_type": token_contract.GITHUB_OAUTH_REFRESH_GRANT_TYPE,
        "refresh_token": _required_string(refresh_token, "refresh_token"),
    }
    if client_secret and client_secret.strip():
        params["client_secret"] = client_secret.strip()
    payload = _oauth_request(
        f"{validated_web_url(login_base)}"
        f"{token_contract.GITHUB_OAUTH_ACCESS_TOKEN_PATH}",
        params, opener=opener, timeout_seconds=timeout_seconds,
    )
    error_code = str(payload.get("error") or "").strip()
    if error_code:
        description = str(payload.get("error_description") or error_code)
        raise GitHubCredentialStoreError(
            f"GitHub App user-token refresh was refused ({error_code}): "
            f"{description}. Run `yoke github connect` to authorize again"
        )
    return credential_document_from_token_response(payload, now=now)


def read_credential_document(path: str | Path) -> dict[str, Any]:
    try:
        payload = credential_file.read_json_document(path)
    except credential_file.CredentialFileError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise GitHubCredentialStoreError(
            "GitHub App credential has an unsupported format; reconnect GitHub"
        )
    _required_string(payload.get("access_token"), "access_token")
    _required_string(payload.get("refresh_token"), "refresh_token")
    _parse_timestamp(payload.get("expires_at"), "expires_at")
    _parse_timestamp(payload.get("refresh_expires_at"), "refresh_expires_at")
    return payload


def write_credential_document(path: str | Path, payload: Mapping[str, Any]) -> Path:
    try:
        return credential_file.write_json_document(path, payload)
    except (credential_file.CredentialFileError, OSError) as exc:
        raise GitHubCredentialStoreError(
            f"GitHub App credential could not be saved: {Path(path).expanduser()}"
        ) from exc


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    try:
        with credential_file.exclusive_lock(path):
            yield
    except credential_file.CredentialFileError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc


def load_config(config_path: str | Path | None) -> dict[str, Any]:
    if config_path is None:
        raise GitHubCredentialStoreError("machine config path is required")
    selected = Path(config_path).expanduser()
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GitHubCredentialStoreError(
            f"machine config is unreadable: {selected}"
        ) from exc
    except ValueError as exc:
        raise GitHubCredentialStoreError(
            f"machine config is not valid JSON: {selected}"
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubCredentialStoreError("machine config must contain an object")
    return payload


def validated_web_url(value: str) -> str:
    try:
        return github_origin.validate_github_web_endpoint(value).base_url
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubCredentialStoreError(str(exc).replace("API URL", "web URL")) from exc


def _oauth_request(
    url: str, params: Mapping[str, str], *, opener: Callable[..., Any] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(params).encode("utf-8"),
        headers={"Accept": token_contract.GITHUB_JSON_ACCEPT,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": token_contract.GITHUB_APP_USER_AGENT}, method="POST",
    )
    try:
        with (opener or _urlopen)(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise GitHubCredentialStoreError(
            f"GitHub App user-token refresh failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise GitHubCredentialStoreError(
            f"GitHub App user-token refresh failed: {exc.reason}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubCredentialStoreError(
            "GitHub App user-token response is not JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubCredentialStoreError(
            "GitHub App user-token response must be an object"
        )
    return payload


def _result(payload: Mapping[str, Any], *, path: Path,
            cached: bool, rotated: bool) -> dict[str, Any]:
    result = dict(payload)
    result.update({"cached": cached, "refresh_rotated": rotated,
                   "refresh_credential_ref": str(path)})
    return result


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise GitHubCredentialStoreError(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise GitHubCredentialStoreError(f"{label} is required")
    return text


def _expiry_timestamp(value: Any, *, now: datetime, label: str) -> datetime:
    if isinstance(value, bool):
        raise GitHubCredentialStoreError(f"{label} must be a positive integer")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubCredentialStoreError(
            f"{label} must be a positive integer"
        ) from exc
    if seconds <= 0:
        raise GitHubCredentialStoreError(f"{label} must be a positive integer")
    return now + timedelta(seconds=seconds)


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        return _ensure_utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError) as exc:
        raise GitHubCredentialStoreError(f"{label} must be an ISO timestamp") from exc


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
