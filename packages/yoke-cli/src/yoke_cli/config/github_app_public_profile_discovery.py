"""Credential-free public GitHub App profile discovery over Yoke health."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from yoke_cli.api_urls import HEALTH_PATH, join_api_url
from yoke_cli.config import github_response_safety
from yoke_contracts import github_app_tokens
from yoke_contracts.github_app_public import (
    GitHubAppPublicProfile,
    parse_github_app_advertisement,
)

HEALTH_TIMEOUT_SECONDS = 5.0


class GitHubAppPublicProfileError(RuntimeError):
    """The selected Yoke service cannot provide a safe public App profile."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


DEFAULT_URLOPEN = urllib.request.build_opener(_NoRedirectHandler()).open


def validated_service_root(service_api_url: str) -> str:
    service_root = str(service_api_url).strip().rstrip("/")
    parsed_service = urllib.parse.urlsplit(service_root)
    if (
        parsed_service.scheme != "https"
        or not parsed_service.hostname
        or parsed_service.username is not None
        or parsed_service.password is not None
        or parsed_service.query
        or parsed_service.fragment
    ):
        raise GitHubAppPublicProfileError(
            "Yoke GitHub App discovery requires a credential-free HTTPS service URL"
        )
    return service_root


def fetch(
    service_api_url: str,
    *,
    opener: Callable[..., Any],
    timeout_seconds: float = HEALTH_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> GitHubAppPublicProfile:
    """Fetch a credential-free, redirect-denied health advertisement."""

    service_root = validated_service_root(service_api_url)
    health_url = join_api_url(service_root, HEALTH_PATH)
    request = urllib.request.Request(
        health_url,
        headers={"Accept": "application/json", "User-Agent": "yoke-cli"},
        method="GET",
    )
    try:
        deadline = monotonic() + timeout_seconds
        with opener(request, timeout=timeout_seconds) as response:
            response_url = getattr(response, "geturl", None)
            if not callable(response_url) or response_url() != health_url:
                raise GitHubAppPublicProfileError(
                    "Yoke GitHub App discovery refused a redirected health response"
                )
            raw = github_response_safety.read_bounded(
                response,
                maximum_bytes=github_app_tokens.GITHUB_OAUTH_RESPONSE_MAX_BYTES,
                deadline=deadline,
                monotonic=monotonic,
            )
    except urllib.error.HTTPError as exc:
        raise GitHubAppPublicProfileError(
            f"Yoke GitHub App discovery failed with HTTP {exc.code} at "
            f"{health_url}; retry when the selected Yoke service is healthy"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubAppPublicProfileError(
            f"Yoke GitHub App discovery could not reach {health_url}; retry "
            "when the selected Yoke service is available"
        ) from exc
    except github_response_safety.GitHubResponseReadError as exc:
        if "too large" in str(exc):
            raise GitHubAppPublicProfileError(
                "Yoke health response is too large to trust for GitHub App discovery"
            ) from exc
        raise GitHubAppPublicProfileError(
            "Yoke GitHub App discovery exceeded its operation deadline"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubAppPublicProfileError(
            "Yoke health response is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise GitHubAppPublicProfileError("Yoke health response must be an object")
    try:
        advertisement = parse_github_app_advertisement(
            payload.get("github_app", {"available": False})
        )
    except (TypeError, ValueError) as exc:
        raise GitHubAppPublicProfileError(
            "Yoke health returned an invalid GitHub App advertisement"
        ) from exc
    if not isinstance(advertisement, GitHubAppPublicProfile):
        raise GitHubAppPublicProfileError(
            "GitHub App connection is unavailable for the selected Yoke service; "
            "a self-hosted operator must configure the public App profile"
        )
    return advertisement
