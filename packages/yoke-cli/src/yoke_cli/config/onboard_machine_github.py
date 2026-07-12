"""Machine GitHub branch for ``yoke onboard``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_contracts import github_origin
from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_machine
from yoke_cli.config import machine_config

CHOICE_CONNECT = "connect"
CHOICE_SKIP = "skip"
CHOICE_LATER = "later"
CHOICES = (CHOICE_SKIP, CHOICE_CONNECT, CHOICE_LATER)


class OnboardMachineGithubError(RuntimeError):
    """Machine GitHub onboarding cannot proceed."""


def plan(
    *,
    choice: str,
    api_url: str | None,
) -> dict[str, Any]:
    selected = normalize_choice(choice)
    return {
        "choice": selected,
        "applied": False,
        "api_url": api_url or github_origin.DEFAULT_GITHUB_API_URL,
        "authorization_source": {
            "kind": "github_app" if selected == CHOICE_CONNECT else "none",
        },
        "writes_machine_secret": selected == CHOICE_CONNECT,
        "requires_browser_flow": selected == CHOICE_CONNECT,
    }


def apply(
    *,
    choice: str,
    config_path: Path,
    api_url: str | None,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> dict[str, Any]:
    selected = normalize_choice(choice)
    if selected != CHOICE_CONNECT:
        return plan(
            choice=selected,
            api_url=api_url,
        )
    if bool(str(service_api_url or "").strip()) == local_connection_selected:
        raise OnboardMachineGithubError(
            "GitHub onboarding requires exactly one local or HTTPS Yoke "
            "connection selection"
        )
    try:
        existing = machine_config.github_config(config_path)
        if existing:
            if api_url:
                try:
                    requested_endpoint = github_origin.validate_github_api_endpoint(
                        api_url
                    )
                    existing_endpoint = github_origin.validate_github_api_endpoint(
                        str(existing.get("api_url") or "")
                    )
                except github_origin.GitHubApiOriginError as exc:
                    raise OnboardMachineGithubError(str(exc)) from exc
                if requested_endpoint.base_url != existing_endpoint.base_url:
                    raise OnboardMachineGithubError(
                        "the existing machine GitHub connection uses a different "
                        "API origin; disconnect and reconnect GitHub for the "
                        "requested deployment"
                    )
            report = github_machine.status(
                config_path=config_path,
                check=True,
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            )
        else:
            if api_url and local_connection_selected:
                requested_endpoint = github_origin.validate_github_api_endpoint(
                    api_url
                )
                bundled_endpoint = github_origin.validate_github_api_endpoint(
                    github_app_public_profile.bundled_local_product_profile().api_url
                )
                if requested_endpoint.base_url != bundled_endpoint.base_url:
                    raise OnboardMachineGithubError(
                        "the requested GitHub API origin does not match the "
                        "bundled local product App"
                    )
            report = github_machine.connect(
                config_path=config_path,
                service_api_url=service_api_url,
                use_local_product_profile=local_connection_selected,
            )
    except (
        github_machine.GitHubMachineError,
        github_app_public_profile.GitHubAppPublicProfileError,
        github_origin.GitHubApiOriginError,
    ) as exc:
        raise OnboardMachineGithubError(str(exc)) from exc
    if not report.get("ok") or not report.get("ready"):
        issues = report.get("issues") or []
        first = issues[0] if issues else {}
        raise OnboardMachineGithubError(
            str(first.get("message") or "GitHub App connection is unavailable")
        )
    return report


def normalize_choice(choice: str | None) -> str:
    selected = (choice or CHOICE_SKIP).strip()
    if selected not in CHOICES:
        raise OnboardMachineGithubError(
            f"unknown machine GitHub choice {selected!r}; expected one of "
            f"{', '.join(CHOICES)}"
        )
    return selected


__all__ = [
    "CHOICE_CONNECT",
    "CHOICE_LATER",
    "CHOICE_SKIP",
    "OnboardMachineGithubError",
    "apply",
    "normalize_choice",
    "plan",
]
