"""Machine and project onboarding for the product ``yoke`` CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from yoke_contracts.machine_config import schema as machine_schema

from yoke_cli.config import local_universe_setup
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_apply_connection
from yoke_cli.config import onboard_bridge
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_credential_replacement
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_report
from yoke_cli.config import onboard_reuse_state
from yoke_cli.config import onboard_apply_progress
from yoke_cli.config import writer
from yoke_cli.config import secrets as machine_secrets

PROJECT_MODE_MACHINE_ONLY = onboard_project.PROJECT_MODE_MACHINE_ONLY
PROJECT_MODE_CREATE_REPO = onboard_project.PROJECT_MODE_CREATE_REPO
PROJECT_MODE_CLONE_REMOTE = onboard_project.PROJECT_MODE_CLONE_REMOTE
PROJECT_MODE_IMPORT_REMOTE = onboard_project.PROJECT_MODE_IMPORT_REMOTE
PROJECT_MODE_LOCAL_CHECKOUT = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
PROJECT_MODE_SOURCE_DEV_ADMIN = onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
PROJECT_MODES = onboard_project.PROJECT_MODES


class OnboardError(RuntimeError):
    """Onboarding cannot proceed; message names the repair."""


def build_report(
    *,
    config_path: str | Path | None,
    env_name: str,
    api_url: str,
    destination: str = onboard_destinations.DEFAULT_DESTINATION,
    token: str | None = None,
    token_file: str | Path | None = None,
    token_source_kind: str = "argument",
    mode: str,
    apply: bool,
    check_identity: bool,
    machine_github_choice: str = onboard_machine_github.CHOICE_SKIP,
    machine_github_api_url: str | None = None,
    project_mode: str = PROJECT_MODE_MACHINE_ONLY,
    project_remote_url: str | None = None,
    project_checkout: str | Path | None = None,
    project_slug: str | None = None,
    project_name: str | None = None,
    project_org: str | None = None,
    project_github_repo: str | None = None,
    project_github_repository_id: int | None = None,
    project_github_installation_id: int | None = None,
    project_default_branch: str | None = None,
    project_default_branch_source: str | None = None,
    project_public_item_prefix: str | None = None,
    existing_project_id: int | None = None,
    existing_project_match_source: str | None = None,
    existing_project_local_source: str | None = None,
    project_github_adoption: str | None = None,
    project_github_adoption_preserve: bool = False,
    project_publish: onboard_project.PublishRequest | None = None,
    project_clone: onboard_project.ClonePlan | None = None,
    project_keep_existing_remote: bool = False,
    progress: onboard_apply_progress.ProgressCallback | None = None,
) -> Dict[str, Any]:
    """Return the onboarding report, applying the write plan when requested."""
    cfg_path = machine_config.config_path(config_path)
    destination = (
        str(destination or "").strip() or onboard_destinations.DEFAULT_DESTINATION
    )
    if destination not in onboard_destinations.DESTINATIONS:
        raise OnboardError(
            f"unknown onboarding destination {destination!r}; expected one of "
            + ", ".join(onboard_destinations.DESTINATIONS)
        )
    local_destination = destination == onboard_destinations.DESTINATION_LOCAL
    if local_destination:
        # The local universe owns its env label and has no sign-in surface:
        # the connection credential is the machine-local DSN reference the
        # birth machinery records, never an API token.
        env_name = local_universe_setup.LOCAL_ENV
        api_url = ""
        source = {"kind": "local-universe"}
        credential_source = {"kind": machine_schema.CREDENTIAL_KIND_DSN_FILE}
    else:
        source = _token_source_summary(
            token=token, token_file=token_file, source_kind=token_source_kind,
        )
        credential_source = _credential_source_plan(cfg_path, env_name)
    normalized_project_mode = onboard_bridge.normalize_project_mode(
        project_mode, error_cls=OnboardError,
    )
    project_inputs = onboard_bridge.project_inputs(
        error_cls=OnboardError,
        project_mode=normalized_project_mode,
        project_remote_url=project_remote_url,
        project_checkout=project_checkout,
        project_slug=project_slug,
        project_name=project_name,
        project_org=project_org,
        project_github_repo=project_github_repo,
        project_github_repository_id=project_github_repository_id,
        project_github_installation_id=project_github_installation_id,
        project_default_branch=project_default_branch,
        project_public_item_prefix=project_public_item_prefix,
        existing_project_id=existing_project_id,
        existing_project_match_source=existing_project_match_source,
        existing_project_local_source=existing_project_local_source,
        project_github_adoption=project_github_adoption,
        project_github_adoption_preserve=project_github_adoption_preserve,
        project_publish=project_publish,
        project_clone=project_clone,
        project_keep_existing_remote=project_keep_existing_remote,
        project_default_branch_source=project_default_branch_source,
    )
    machine_github = onboard_bridge.machine_github(
        onboard_machine_github.plan,
        error_cls=OnboardError,
        choice=machine_github_choice,
        api_url=machine_github_api_url,
    )
    reuse = onboard_reuse_state.detect(
        cfg_path=cfg_path,
        env_name=env_name,
        api_url=api_url,
        credential_source=credential_source,
        source=source,
        project_inputs=project_inputs,
        machine_github=machine_github,
    )
    if reuse.get("machine_github"):
        machine_github = {
            **machine_github,
            "writes_machine_secret": False,
            "requires_browser_flow": False,
            "reused": True,
        }
    plan = onboard_report.build_plan(
        cfg_path, env_name, api_url, credential_source, source, mode,
        project_mode=normalized_project_mode, project_inputs=project_inputs,
        machine_github=machine_github,
        reuse=reuse,
        local_destination=local_destination,
    )
    report: Dict[str, Any] = {
        "operation": "onboard",
        "mode": mode,
        "destination": destination,
        "project_mode": normalized_project_mode,
        "applied": False,
        "config": str(cfg_path),
        "config_path": str(cfg_path),
        "plan": plan,
        "identity": {"checked": False, "ok": None},
        "machine_github": machine_github,
        "next_steps": onboard_report.next_steps(cfg_path, normalized_project_mode),
    }
    if normalized_project_mode != PROJECT_MODE_MACHINE_ONLY:
        report["project_onboarding"] = onboard_bridge.project_report(
            error_cls=OnboardError,
            config_path=cfg_path,
            apply=False,
            project_inputs=project_inputs,
            reuse=reuse,
            service_api_url=api_url or None,
        )
    if not apply:
        report["message"] = "write plan only; rerun with --yes to apply"
        return report
    onboard_bridge.preflight_project_apply(
        report.get("project_onboarding"), error_cls=OnboardError,
    )
    problems = onboard_credential_replacement.replacement_problems_from_kwargs(locals())
    if problems:
        raise OnboardError(" ".join(problems))
    if local_destination:
        onboard_apply_connection.apply_local_universe(
            cfg_path, env_name, reuse, progress, report,
            error_cls=OnboardError,
        )
    else:
        onboard_apply_connection.apply_sign_in_connection(
            cfg_path, env_name, api_url, reuse, progress, report,
            token=token, token_file=token_file,
            token_source_kind=token_source_kind, check_identity=check_identity,
            error_cls=OnboardError,
        )
    runtime_steps = tuple(
        step for step in (
            None if reuse.get("temp_root") else ("create-runtime-dir", "temp_root"),
            None if reuse.get("cache_dir") else ("create-runtime-dir", "cache_dir"),
        )
        if step is not None
    )
    if runtime_steps:
        onboard_apply_progress.emit_many(progress, runtime_steps, "running")
        writer.set_runtime_paths(
            temp_root=cfg_path.parent / "tmp",
            cache_dir=cfg_path.parent / "cache",
            path=cfg_path,
        )
        _ensure_runtime_dirs(cfg_path)
        onboard_apply_progress.emit_many(progress, runtime_steps, "done")
    if reuse.get("machine_github"):
        report["machine_github"] = dict(machine_github)
    else:
        onboard_apply_progress.emit(
            progress, "machine-github-connection", machine_github_choice, "running"
        )
        report["machine_github"] = onboard_bridge.machine_github(
            onboard_machine_github.apply,
            error_cls=OnboardError,
            choice=machine_github_choice,
            config_path=cfg_path,
            api_url=machine_github_api_url,
            service_api_url=api_url or None,
        )
        onboard_apply_progress.emit(
            progress, "machine-github-connection", machine_github_choice, "done"
        )
    report["applied"] = True
    report["message"] = "machine config written"
    if normalized_project_mode != PROJECT_MODE_MACHINE_ONLY:
        source_target = onboard_report.source_choice_target(
            normalized_project_mode, project_inputs
        )
        if not reuse.get("project_identity"):
            onboard_apply_progress.emit(
                progress, "project-source-choice", source_target, "done"
            )
        report["project_onboarding"] = onboard_bridge.project_report(
            error_cls=OnboardError,
            config_path=cfg_path,
            apply=True,
            project_inputs=project_inputs,
            reuse=reuse,
            progress=progress,
            service_api_url=api_url or None,
        )
        report["message"] = "machine config and project handoff written"
    return report


def dumps_json(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"
def render_human(report: Dict[str, Any]) -> str:
    return onboard_report.render_human(report)

def _credential_source_plan(
    cfg_path: Path,
    env_name: str,
) -> dict[str, Any]:
    return {"kind": "token_file", "path": str(machine_secrets.secret_path(env_name, "token"))}


def _token_source_summary(
    *,
    token: str | None,
    token_file: str | Path | None,
    source_kind: str,
) -> dict[str, Any]:
    if token_file is not None:
        return {"kind": "token_file", "path": str(Path(token_file).expanduser())}
    if token:
        return {"kind": source_kind}
    return {"kind": "missing"}


def _ensure_runtime_dirs(config_path: Path) -> None:
    Path(machine_config.temp_root(config_path)).mkdir(parents=True, exist_ok=True)
    machine_config.cache_dir(config_path).mkdir(parents=True, exist_ok=True)


__all__ = [
    "OnboardError", "PROJECT_MODE_CLONE_REMOTE", "PROJECT_MODE_CREATE_REPO",
    "PROJECT_MODE_IMPORT_REMOTE", "PROJECT_MODE_LOCAL_CHECKOUT",
    "PROJECT_MODE_MACHINE_ONLY", "PROJECT_MODE_SOURCE_DEV_ADMIN", "PROJECT_MODES",
    "build_report", "dumps_json", "render_human",
]
