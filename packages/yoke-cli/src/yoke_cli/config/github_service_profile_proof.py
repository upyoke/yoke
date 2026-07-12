"""Live proof that a service still advertises the cached public App identity."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

if __package__:
    from yoke_contracts import api_urls, github_app_tokens, github_origin
    from yoke_cli.config import github_response_safety
else:  # pragma: no cover - immutable helper bundle imports sibling copies
    import _yoke_api_urls as api_urls  # type: ignore
    import _yoke_github_app_tokens as github_app_tokens  # type: ignore
    import _yoke_github_origin as github_origin  # type: ignore
    import _yoke_github_response_safety as github_response_safety  # type: ignore


PROFILE_TIMEOUT_SECONDS = 5.0
_PROFILE_FIELDS = ("client_id", "app_slug", "app_id", "api_url", "web_url")
_ADVERTISEMENT_KEYS = frozenset({"available", *_PROFILE_FIELDS})


class GitHubServiceProfileProofError(RuntimeError):
    """The selected service did not prove the cached public App identity."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def prove(
    github: Mapping[str, Any],
    service_api_url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout_seconds: float = PROFILE_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Fetch exact service health and compare all five nonsecret App fields."""

    root = _service_root(service_api_url)
    health_url = api_urls.join_api_url(root, api_urls.HEALTH_PATH)
    request = urllib.request.Request(
        health_url,
        headers={"Accept": "application/json", "User-Agent": "yoke-cli"},
        method="GET",
    )
    deadline = monotonic() + timeout_seconds
    try:
        with (opener or _urlopen)(request, timeout=timeout_seconds) as response:
            final_url = getattr(response, "geturl", None)
            if not callable(final_url) or final_url() != health_url:
                raise GitHubServiceProfileProofError(
                    "selected Yoke service redirected its App identity proof"
                )
            raw = github_response_safety.read_bounded(
                response,
                maximum_bytes=github_app_tokens.GITHUB_OAUTH_RESPONSE_MAX_BYTES,
                deadline=deadline,
                monotonic=monotonic,
            )
    except GitHubServiceProfileProofError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise GitHubServiceProfileProofError(
            "selected Yoke service could not prove its GitHub App identity"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        raise GitHubServiceProfileProofError(
            "selected Yoke service App identity proof exceeded its safety boundary"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubServiceProfileProofError(
            "selected Yoke service App identity proof is invalid"
        ) from exc
    advertisement = payload.get("github_app") if isinstance(payload, Mapping) else None
    if not isinstance(advertisement, Mapping) or set(advertisement) != _ADVERTISEMENT_KEYS:
        raise GitHubServiceProfileProofError(
            "selected Yoke service App identity proof is incomplete"
        )
    actual = _normalized_profile(advertisement)
    expected = _normalized_profile(github)
    if actual != expected:
        raise GitHubServiceProfileProofError(
            "selected Yoke service now advertises a different GitHub App; reconnect"
        )


def prove_local_product(github: Mapping[str, Any]) -> None:
    """Prove a saved local-product identity against this release's bundle."""

    expected_values = github_app_tokens.local_product_profile_values()
    if expected_values is None:
        raise GitHubServiceProfileProofError(
            "this Yoke release does not contain a local product GitHub App "
            "identity; reconnect with a release that does"
        )
    actual = _normalized_profile(github)
    expected = _normalized_profile(expected_values)
    if actual != expected:
        raise GitHubServiceProfileProofError(
            "saved local product GitHub App identity differs from this Yoke "
            "release; reconnect"
        )


def selected_service_api_url(
    config: Mapping[str, Any],
    github: Mapping[str, Any],
    *,
    expected_service_api_url: str | None = None,
    expected_local_connection: bool = False,
) -> str | None:
    """Validate saved profile provenance against the selected connection."""

    if expected_local_connection and str(expected_service_api_url or "").strip():
        raise GitHubServiceProfileProofError(
            "a local Yoke connection cannot also select an HTTPS service"
        )
    if expected_local_connection:
        if github.get("profile_service_api_url") in (None, "") and github.get(
            "profile_source"
        ) in {
            github_app_tokens.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
            github_app_tokens.GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
        }:
            return None
        raise GitHubServiceProfileProofError(
            "saved GitHub App profile does not match the requested local Yoke "
            "connection; reconnect GitHub"
        )
    if str(expected_service_api_url or "").strip():
        selected = str(expected_service_api_url).strip().rstrip("/")
        saved = str(github.get("profile_service_api_url") or "").rstrip("/")
        if (
            github.get("profile_source")
            == github_app_tokens.GITHUB_PROFILE_SOURCE_SERVICE
            and saved == selected
        ):
            return selected
        raise GitHubServiceProfileProofError(
            "saved GitHub App profile does not match the requested Yoke "
            "service; reconnect GitHub"
        )
    active_env = (
        os.environ.get(github_app_tokens.YOKE_ENV_OVERRIDE_NAME, "").strip()
        or str(config.get("active_env") or "").strip()
    )
    connections = config.get("connections")
    connection = (
        connections.get(active_env)
        if isinstance(connections, Mapping) and active_env else None
    )
    if not isinstance(connection, Mapping):
        raise GitHubServiceProfileProofError(
            "active Yoke connection is unavailable; reconnect GitHub"
        )
    source = github.get("profile_source")
    if str(connection.get("transport") or "") == "https":
        selected = _service_root(str(connection.get("api_url") or ""))
        saved = str(github.get("profile_service_api_url") or "").rstrip("/")
        if (
            source == github_app_tokens.GITHUB_PROFILE_SOURCE_SERVICE
            and saved == selected
        ):
            return selected
    elif not connection.get("api_url") and github.get(
        "profile_service_api_url"
    ) in (None, "") and source in {
        github_app_tokens.GITHUB_PROFILE_SOURCE_LOCAL_EXPLICIT,
        github_app_tokens.GITHUB_PROFILE_SOURCE_LOCAL_PRODUCT,
    }:
        return None
    raise GitHubServiceProfileProofError(
        "saved GitHub App profile does not match the active Yoke connection; "
        "reconnect GitHub"
    )


def _normalized_profile(values: Mapping[str, Any]) -> dict[str, Any]:
    if values.get("available", True) is not True:
        raise GitHubServiceProfileProofError(
            "selected Yoke service does not advertise an available GitHub App"
        )
    app_id = values.get("app_id")
    if isinstance(app_id, bool) or not isinstance(app_id, int) or app_id <= 0:
        raise GitHubServiceProfileProofError("GitHub App identity is invalid")
    client_id = str(values.get("client_id") or "").strip()
    app_slug = str(values.get("app_slug") or "").strip()
    if not client_id or not app_slug:
        raise GitHubServiceProfileProofError("GitHub App identity is incomplete")
    try:
        pair = github_origin.validate_github_endpoint_pair(
            str(values.get("api_url") or ""), str(values.get("web_url") or ""),
        )
        pair.app_install_url(app_slug)
    except github_origin.GitHubApiOriginError as exc:
        raise GitHubServiceProfileProofError("GitHub App identity is invalid") from exc
    return {
        "client_id": client_id,
        "app_slug": app_slug,
        "app_id": app_id,
        "api_url": pair.api.base_url,
        "web_url": pair.web.base_url,
    }


def _service_root(value: str) -> str:
    selected = str(value or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(selected)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment
    ):
        raise GitHubServiceProfileProofError(
            "selected Yoke service URL is not a credential-free HTTPS URL"
        )
    return selected


__all__ = [
    "GitHubServiceProfileProofError",
    "PROFILE_TIMEOUT_SECONDS",
    "prove",
    "prove_local_product",
    "selected_service_api_url",
]
