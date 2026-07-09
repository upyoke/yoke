"""Machine GitHub branch for ``yoke onboard``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_machine

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
    token_file: str | None,
    token_source_kind: str | None,
) -> dict[str, Any]:
    selected = normalize_choice(choice)
    return {
        "choice": selected,
        "applied": False,
        "api_url": api_url or "https://api.github.com",
        "authorization_source": {
            "kind": "github_app" if selected == CHOICE_CONNECT else "none",
        },
        "writes_machine_secret": False,
        "requires_browser_flow": selected == CHOICE_CONNECT,
    }


def apply(
    *,
    choice: str,
    config_path: Path,
    api_url: str | None,
    token: str | None,
    token_file: str | None,
    token_source_kind: str | None,
) -> dict[str, Any]:
    selected = normalize_choice(choice)
    if selected != CHOICE_CONNECT:
        return plan(
            choice=selected,
            api_url=api_url,
            token_file=token_file,
            token_source_kind=token_source_kind,
        )
    try:
        report = github_machine.connect(
            config_path=config_path,
            token=token,
            token_file=token_file,
            token_source_kind=token_source_kind or "prompt",
            api_url=api_url,
        )
    except github_machine.GitHubMachineError as exc:
        raise OnboardMachineGithubError(str(exc)) from exc
    if not report.get("ok"):
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
