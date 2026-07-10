"""Exception-normalizing wrappers around onboarding sub-flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project


def normalize_project_mode(project_mode: str | None, *, error_cls) -> str:
    try:
        return onboard_project.normalize_project_mode(project_mode)
    except onboard_project.OnboardProjectError as exc:
        raise error_cls(str(exc)) from exc


def project_inputs(
    *,
    error_cls,
    project_mode: str,
    project_remote_url: str | None,
    project_checkout: str | Path | None,
    project_slug: str | None,
    project_name: str | None,
    project_org: str | None,
    project_github_repo: str | None,
    project_default_branch: str | None,
    project_public_item_prefix: str | None,
    existing_project_id: int | None,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_github_adoption: str | None = None,
    project_publish: onboard_project.PublishRequest | None = None,
    project_clone: onboard_project.ClonePlan | None = None,
    project_keep_existing_remote: bool = False,
    project_default_branch_source: str | None = None,
) -> dict[str, Any]:
    try:
        return onboard_project.project_inputs(
            project_mode=project_mode,
            project_remote_url=project_remote_url,
            project_checkout=project_checkout,
            project_slug=project_slug,
            project_name=project_name,
            project_org=project_org,
            project_github_repo=project_github_repo,
            project_default_branch=project_default_branch,
            project_public_item_prefix=project_public_item_prefix,
            existing_project_id=existing_project_id,
            existing_project_match_source=existing_project_match_source,
            existing_project_local_source=existing_project_local_source,
            project_github_adoption=project_github_adoption,
            project_publish=project_publish,
            project_clone=project_clone,
            project_keep_existing_remote=project_keep_existing_remote,
            project_default_branch_source=project_default_branch_source,
        )
    except onboard_project.OnboardProjectError as exc:
        raise error_cls(str(exc)) from exc


def machine_github(fn, *, error_cls, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(**kwargs)
    except onboard_machine_github.OnboardMachineGithubError as exc:
        raise error_cls(str(exc)) from exc


def project_report(
    *,
    error_cls,
    config_path: Path,
    apply: bool,
    project_inputs: dict[str, Any],
    reuse: Mapping[str, Any],
    progress: onboard_apply_progress.ProgressCallback | None = None,
) -> dict[str, Any]:
    try:
        return onboard_project.project_report(
            inputs=project_inputs,
            config_path=config_path,
            apply=apply,
            reuse=reuse,
            progress=progress,
        )
    except onboard_project.OnboardProjectError as exc:
        raise error_cls(str(exc)) from exc


def preflight_project_apply(project_report: Any, *, error_cls) -> None:
    try:
        onboard_project.preflight_project_apply(project_report)
    except onboard_project.OnboardProjectError as exc:
        raise error_cls(str(exc)) from exc


__all__ = [
    "machine_github",
    "normalize_project_mode",
    "preflight_project_apply",
    "project_inputs",
    "project_report",
]
