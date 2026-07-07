"""Onboarding checks for machine credential replacement conflicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_machine_github
from yoke_cli.config import secrets as machine_secrets


def replacement_problems_from_result(result: Any) -> list[str]:
    return replacement_problems(
        env_name=str(getattr(result, "env_name", "") or ""),
        token=getattr(result, "token", None),
        token_file=getattr(result, "token_file", None),
        machine_github_choice=getattr(result, "machine_github_choice", None),
        machine_github_token=getattr(result, "machine_github_token", None),
        machine_github_token_file=getattr(result, "machine_github_token_file", None),
    )


def replacement_problems_from_kwargs(kwargs: dict[str, Any]) -> list[str]:
    return replacement_problems(
        env_name=str(kwargs.get("env_name") or ""),
        token=kwargs.get("token"),
        token_file=kwargs.get("token_file"),
        machine_github_choice=kwargs.get("machine_github_choice"),
        machine_github_token=kwargs.get("machine_github_token"),
        machine_github_token_file=kwargs.get("machine_github_token_file"),
    )


def replacement_problems(
    *,
    env_name: str,
    token: str | None,
    token_file: str | Path | None,
    machine_github_choice: str | None,
    machine_github_token: str | None,
    machine_github_token_file: str | Path | None,
) -> list[str]:
    problems: list[str] = []
    selected_env = env_name.strip() or "prod"
    yoke_problem = _replacement_problem(
        label=f"Yoke API token for {selected_env}",
        target=machine_secrets.secret_path_no_create(selected_env, "token"),
        incoming=_incoming_secret(token=token, token_file=token_file),
        guidance="remove the saved token file or rerun onboarding with that token",
    )
    if yoke_problem:
        problems.append(yoke_problem)

    if machine_github_choice == onboard_machine_github.CHOICE_CONNECT:
        github_problem = _replacement_problem(
            label="machine GitHub token",
            target=machine_secrets.secret_path_no_create("github", "token"),
            incoming=_incoming_secret(
                token=machine_github_token,
                token_file=machine_github_token_file,
            ),
            guidance="remove the saved GitHub token file or skip connecting GitHub",
        )
        if github_problem:
            problems.append(github_problem)
    return problems


def _replacement_problem(
    *,
    label: str,
    target: Path,
    incoming: str | None,
    guidance: str,
) -> str | None:
    if not incoming:
        return None
    if not target.exists():
        return None
    try:
        existing = target.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            f"An existing {label} is saved at {target}, but Yoke cannot read "
            "it to confirm this is the same token."
        )
    if not existing or existing == incoming.strip():
        return None
    return (
        f"This machine already has a different {label} saved at {target}; "
        f"{guidance}. Yoke will not overwrite it silently."
    )


def _incoming_secret(
    *,
    token: str | None,
    token_file: str | Path | None,
) -> str | None:
    if token_file is not None:
        try:
            return machine_secrets.read_secret_file(token_file, "token")
        except machine_secrets.MachineSecretError:
            return None
    value = (token or "").strip()
    return value or None


__all__ = [
    "replacement_problems",
    "replacement_problems_from_kwargs",
    "replacement_problems_from_result",
]
