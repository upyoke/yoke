"""Machine GitHub branch for ``yoke onboard``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_machine

CHOICE_CONNECT = "connect"
CHOICE_SKIP = "skip"
CHOICE_LATER = "later"
CHOICE_TOKEN_FILE = "file"
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
        "token_source": _token_source(token_file, token_source_kind),
        "writes_machine_secret": selected == CHOICE_CONNECT,
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
        return github_machine.connect(
            config_path=config_path,
            token=token,
            token_file=token_file,
            token_source_kind=token_source_kind or "prompt",
            api_url=api_url,
        )
    except github_machine.GitHubMachineError as exc:
        raise OnboardMachineGithubError(str(exc)) from exc


def normalize_choice(choice: str | None) -> str:
    selected = (choice or CHOICE_SKIP).strip()
    if selected not in CHOICES:
        raise OnboardMachineGithubError(
            f"unknown machine GitHub choice {selected!r}; expected one of "
            f"{', '.join(CHOICES)}"
        )
    return selected


def _token_source(token_file: str | None, token_source_kind: str | None) -> dict[str, str]:
    if token_file:
        return {"kind": "token_file", "path": token_file}
    return {"kind": token_source_kind or "none"}


__all__ = [
    "CHOICE_CONNECT",
    "CHOICE_LATER",
    "CHOICE_SKIP",
    "CHOICE_TOKEN_FILE",
    "OnboardMachineGithubError",
    "apply",
    "normalize_choice",
    "plan",
]
