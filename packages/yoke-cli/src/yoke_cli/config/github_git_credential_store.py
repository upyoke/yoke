"""Atomic refresh-only storage with a serialized refresh-token rotation chain."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
import urllib.parse

if __package__:
    from yoke_cli.config import github_git_credential_document as credential_document
    from yoke_cli.config import github_git_credential_file as credential_file
    from yoke_cli.config import github_machine_operation
    from yoke_cli.config import github_oauth_transport
    from yoke_cli.config import github_response_safety
    from yoke_cli.config import github_service_profile_proof
    from yoke_cli.config.github_git_credential_ownership import (  # noqa: F401
        claim_config_owner,
        credential_document_from_token_response,
        release_config_owner,
    )
    from yoke_contracts import github_app_tokens as token_contract, github_origin

    _MachineOperationError = github_machine_operation.GitHubMachineOperationError
else:  # pragma: no cover - copied helper always uses its immutable siblings
    import _yoke_github_app_tokens as token_contract  # type: ignore
    import _yoke_github_git_credential_document as credential_document  # type: ignore
    import _yoke_github_git_credential_file as credential_file  # type: ignore
    import _yoke_github_origin as github_origin  # type: ignore
    import _yoke_github_oauth_transport as github_oauth_transport  # type: ignore
    import _yoke_github_response_safety as github_response_safety  # type: ignore
    import _yoke_github_service_profile_proof as github_service_profile_proof  # type: ignore

    _MachineOperationError = credential_file.CredentialFileError

CREDENTIAL_SCHEMA_VERSION = 2
DEFAULT_GITHUB_WEB_URL = github_origin.DEFAULT_GITHUB_WEB_URL


class GitHubCredentialStoreError(RuntimeError):
    """The local GitHub App credential cannot provide an access token."""


def access_token_from_machine_config(
    config_path: str | Path | None,
    *,
    opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    client_secret: str | None = None,
    profile_opener: Callable[..., Any] | None = None,
    profile_proven: bool = False,
    expected_service_api_url: str | None = None,
) -> dict[str, Any]:
    with _machine_operation_lock(config_path):
        return access_token_from_config(
            load_config(config_path),
            config_path=config_path,
            opener=opener,
            now=now,
            timeout_seconds=timeout_seconds,
            client_secret=client_secret,
            profile_opener=profile_opener,
            profile_proven=profile_proven,
            expected_service_api_url=expected_service_api_url,
        )


def access_token_for_git_request(
    config_path: str | Path | None,
    fields: Mapping[str, str],
    *,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any] | None:
    """Atomically match a Git credential request and refresh its profile."""

    with _machine_operation_lock(config_path):
        config = load_config(config_path)
        github = config.get("github")
        if not isinstance(github, Mapping) or fields.get("protocol") != "https":
            return None
        expected = urllib.parse.urlsplit(
            validated_web_url(str(github.get("web_url") or DEFAULT_GITHUB_WEB_URL))
        ).netloc
        if fields.get("host", "").casefold() != expected.casefold():
            return None
        return access_token_from_config(
            config,
            config_path=config_path,
            opener=opener,
        )


def access_token_from_config(
    config: Mapping[str, Any],
    *,
    config_path: str | Path | None,
    opener: Callable[..., Any] | None,
    now: datetime | None = None,
    timeout_seconds: float = 30.0,
    client_secret: str | None = None,
    profile_opener: Callable[..., Any] | None = None,
    profile_proven: bool = False,
    expected_service_api_url: str | None = None,
) -> dict[str, Any]:
    github = config.get("github")
    if not isinstance(github, Mapping):
        raise GitHubCredentialStoreError(
            "machine GitHub App authorization is not configured"
        )
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
    path = credential_document.validate_owned_path(
        config_path,
        _required_string(
            authorization.get("refresh_credential_ref"),
            "github.authorization.refresh_credential_ref",
        ),
        error_type=GitHubCredentialStoreError,
    )
    try:
        service_api_url = github_service_profile_proof.selected_service_api_url(
            config,
            github,
            expected_service_api_url=expected_service_api_url,
        )
    except github_service_profile_proof.GitHubServiceProfileProofError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc
    if service_api_url is not None and not profile_proven:
        try:
            github_service_profile_proof.prove(
                github,
                service_api_url,
                opener=profile_opener,
            )
        except github_service_profile_proof.GitHubServiceProfileProofError as exc:
            raise GitHubCredentialStoreError(str(exc)) from exc
    if (
        github.get("profile_source")
        == token_contract.GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT
        and not profile_proven
    ):
        try:
            github_service_profile_proof.prove_local_product(github)
        except github_service_profile_proof.GitHubServiceProfileProofError as exc:
            raise GitHubCredentialStoreError(str(exc)) from exc
    client_id = _required_string(github.get("client_id"), "github.client_id")
    try:
        endpoint_pair = github_origin.validate_github_endpoint_pair(
            str(github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(github.get("web_url") or DEFAULT_GITHUB_WEB_URL),
        )
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc
    selected_now = _ensure_utc(now or datetime.now(timezone.utc))
    with _locked(path):
        current = read_credential_document(path)
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
            write_credential_document(
                path,
                _persisted_document(refreshed, ownership_source=current),
            )
        except GitHubCredentialStoreError as exc:
            raise GitHubCredentialStoreError(
                "GitHub rotated the user credential but its local save failed; "
                "run `yoke github connect` to recover"
            ) from exc
        return _result(refreshed, path=path, cached=False, rotated=rotated)


def refresh_credential_document(
    *,
    client_id: str,
    refresh_token: str,
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
    # Production writes this refresh document only from GitHub's device flow,
    # whose refresh exchange does not require a client secret. Hosted callers
    # may still provide one when their App policy requires it.
    if client_secret and client_secret.strip():
        params["client_secret"] = client_secret.strip()
    try:
        payload = github_oauth_transport.post_form(
            f"{validated_web_url(login_base)}"
            f"{token_contract.GITHUB_OAUTH_ACCESS_TOKEN_PATH}",
            params,
            opener=opener,
            timeout_seconds=timeout_seconds,
        )
    except github_oauth_transport.GitHubOAuthTransportError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc
    raw_error_code = str(payload.get("error") or "").strip()
    if raw_error_code:
        error_code = github_response_safety.safe_oauth_error_code(
            raw_error_code,
            secrets=(refresh_token, client_secret or "", client_id),
        )
        description = github_response_safety.safe_error_text(
            payload.get("error_description") or error_code,
            secrets=(refresh_token, client_secret or "", client_id),
        )
        raise GitHubCredentialStoreError(
            f"GitHub App user-token refresh was refused ({error_code}): "
            f"{description}. Run `yoke github connect` to authorize again"
        )
    return _token_state_from_response(payload, now=now)


def read_credential_document(path: str | Path) -> dict[str, Any]:
    return credential_document.read_document(
        path,
        schema_version=CREDENTIAL_SCHEMA_VERSION,
        error_type=GitHubCredentialStoreError,
    )


def write_credential_document(path: str | Path, payload: Mapping[str, Any]) -> Path:
    return credential_document.write_document(
        path,
        payload,
        error_type=GitHubCredentialStoreError,
    )


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    try:
        with credential_file.exclusive_lock(path):
            yield
    except credential_file.CredentialFileError as exc:
        raise GitHubCredentialStoreError(str(exc)) from exc


@contextmanager
def _machine_operation_lock(
    config_path: str | Path | None,
) -> Iterator[None]:
    try:
        if __package__:
            with github_machine_operation.operation_lock(config_path):
                yield
            return
        if config_path is None:
            raise GitHubCredentialStoreError("machine config path is required")
        target = credential_document.machine_secrets_dir() / ".github-machine-operation"
        with credential_file.exclusive_lock(target):
            yield
    except (credential_file.CredentialFileError, _MachineOperationError) as exc:
        raise GitHubCredentialStoreError(
            "machine GitHub App operation lock is unavailable"
        ) from exc


def load_config(config_path: str | Path | None) -> dict[str, Any]:
    if config_path is None:
        raise GitHubCredentialStoreError("machine config path is required")
    try:
        payload = credential_file.read_json_document(
            config_path,
            require_private_parent=False,
        )
    except credential_file.CredentialFileError as exc:
        raise GitHubCredentialStoreError(
            "machine config is unreadable or unsafe"
        ) from exc
    if not isinstance(payload, dict):
        raise GitHubCredentialStoreError("machine config must contain an object")
    return payload


def validated_web_url(value: str) -> str:
    try:
        return github_origin.validate_github_web_endpoint(value).base_url
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubCredentialStoreError(
            str(exc).replace("API URL", "web URL")
        ) from exc


def _result(
    payload: Mapping[str, Any], *, path: Path, cached: bool, rotated: bool
) -> dict[str, Any]:
    return dict(
        payload,
        cached=cached,
        refresh_rotated=rotated,
        refresh_credential_ref=str(path),
    )


_token_state_from_response = partial(
    credential_document.token_state_from_response,
    error_type=GitHubCredentialStoreError,
)
_persisted_document = partial(
    credential_document.persisted_document,
    schema_version=CREDENTIAL_SCHEMA_VERSION,
    error_type=GitHubCredentialStoreError,
)
_required_string = partial(
    credential_document.required_string,
    error_type=GitHubCredentialStoreError,
)
_parse_timestamp = partial(
    credential_document.parse_timestamp,
    error_type=GitHubCredentialStoreError,
)
_ensure_utc = credential_document.ensure_utc
