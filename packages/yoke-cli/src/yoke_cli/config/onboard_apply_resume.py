"""Run-id resume helpers for ``yoke onboard``."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import onboard_apply_report


class OnboardApplyResumeError(RuntimeError):
    """A stored onboarding apply report cannot be resumed."""


def load_snapshot(run_id: str) -> dict[str, Any]:
    """Load the non-secret input snapshot from a stored apply report."""
    payload = load_payload(run_id)
    snapshot = payload.get("input_snapshot")
    if not isinstance(snapshot, dict):
        raise OnboardApplyResumeError(
            f"run {run_id!r} cannot be resumed; its report has no input snapshot"
        )
    return snapshot


def load_payload(run_id: str) -> dict[str, Any]:
    path = onboard_apply_report.run_report_path(normalize_run_id(run_id))
    if not path.is_file():
        raise OnboardApplyResumeError(f"onboarding run not found: {run_id}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OnboardApplyResumeError(
            f"could not read onboarding run {run_id!r}: {exc}"
        ) from exc
    if payload.get("schema") != onboard_apply_report.SCHEMA_NAME:
        raise OnboardApplyResumeError(
            f"run {run_id!r} is not an onboarding apply report"
        )
    return payload


def apply_defaults(parsed: Any, snapshot: Mapping[str, Any]) -> None:
    """Fill missing argparse fields from a safe input snapshot."""
    _set_missing(parsed, "config_path", snapshot.get("config_path"))
    _set_missing(parsed, "env_name", snapshot.get("env_name"))
    _set_missing(parsed, "api_url", snapshot.get("api_url"))
    _set_missing(parsed, "destination", snapshot.get("destination"))
    project = _mapping(snapshot.get("project"))
    _set_missing(parsed, "project_mode", project.get("mode"))
    _set_missing(parsed, "project_remote_url", project.get("remote_url"))
    _set_missing(parsed, "project_checkout", project.get("checkout"))
    _set_missing(parsed, "project_slug", project.get("slug"))
    _set_missing(parsed, "project_name", project.get("name"))
    _set_missing(parsed, "project_org", project.get("org"))
    _set_missing(parsed, "project_github_repo", project.get("github_repo"))
    _set_missing(parsed, "project_default_branch", project.get("default_branch"))
    _set_missing(
        parsed, "project_default_branch_source",
        project.get("default_branch_source"),
    )
    _set_missing(parsed, "project_public_item_prefix", project.get("public_item_prefix"))
    _set_missing(parsed, "existing_project_id", project.get("existing_project_id"))
    _set_missing(
        parsed,
        "existing_project_match_source",
        project.get("existing_project_match_source"),
    )
    _set_missing(
        parsed,
        "existing_project_local_source",
        project.get("existing_project_local_source"),
    )
    _set_missing(parsed, "github_adoption", project.get("github_adoption"))
    _set_missing(parsed, "github_token_file", project.get("github_token_file"))
    _set_bool_missing(
        parsed, "project_keep_existing_remote", project.get("keep_existing_remote"),
    )
    _restore_publish_defaults(parsed, project.get("publish"))
    clone = _mapping(project.get("clone"))
    _set_missing(parsed, "project_clone_outcome", clone.get("outcome"))
    _set_bool_missing(
        parsed, "project_clone_keep_upstream", clone.get("keep_upstream"),
    )
    _set_missing(parsed, "project_clone_fork_api_url", clone.get("fork_api_url"))
    _restore_publish_defaults(parsed, clone.get("publish"))
    machine_github = _mapping(snapshot.get("machine_github"))
    _set_missing(parsed, "machine_github_choice", machine_github.get("choice"))
    _set_missing(parsed, "machine_github_api_url", machine_github.get("api_url"))
    _set_missing(parsed, "machine_github_token_file", machine_github.get("token_file"))
    _set_missing(
        parsed, "machine_github_token_source_kind",
        machine_github.get("token_source_kind"),
    )
    _restore_token_file(parsed, snapshot)


def start_over(run_id: str, *, confirmed: bool) -> dict[str, Any]:
    """Remove the checkout only when the report proves Yoke created it."""
    if not confirmed:
        raise OnboardApplyResumeError("--start-over requires --yes")
    normalized = normalize_run_id(run_id)
    payload = load_payload(normalized)
    checkout = start_over_checkout_path(normalized)
    if not checkout:
        raise OnboardApplyResumeError(
            f"run {run_id!r} has no checkout Yoke can safely remove"
        )
    removed = _remove_checkout(checkout)
    payload["final_status"] = "started-over"
    payload["start_over"] = {
        "checkout_path": checkout,
        "removed_checkout": removed,
        "remote_repo_removed": False,
    }
    onboard_apply_report.ApplyReportWriter(
        onboard_apply_report.run_report_path(normalized), payload
    ).write()
    return {
        "run_id": normalized,
        "report_path": str(onboard_apply_report.run_report_path(normalized)),
        "checkout_path": checkout,
        "removed_checkout": removed,
        "remote_repo_removed": False,
    }


def start_over_checkout_path(run_id: str) -> str | None:
    """Return the removable checkout path for a run, if the report proves one."""
    payload = load_payload(normalize_run_id(run_id))
    snapshot = payload.get("input_snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    provenance = _mapping(snapshot.get("checkout_provenance"))
    checkout = str(provenance.get("path") or "")
    if checkout and provenance.get("safe_to_remove_on_start_over"):
        return checkout
    return None


def normalize_run_id(run_id: str) -> str:
    selected = str(run_id or "").strip()
    if not selected:
        raise OnboardApplyResumeError("resume run id is empty")
    if "/" in selected or "\\" in selected:
        raise OnboardApplyResumeError(f"invalid onboarding run id: {run_id!r}")
    return selected.removesuffix(".json")


def _restore_token_file(parsed: Any, snapshot: Mapping[str, Any]) -> None:
    sources = _mapping(snapshot.get("token_sources"))
    yoke = _mapping(sources.get("yoke"))
    if not (getattr(parsed, "token", None) or getattr(parsed, "token_file", None)):
        path = str(yoke.get("path") or "")
        if path:
            parsed.token_file = path


def _remove_checkout(value: str) -> bool:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=False)
        home = Path.home().resolve(strict=False)
    except OSError as exc:
        raise OnboardApplyResumeError(
            f"could not resolve checkout path {value!r}: {exc}"
        ) from exc
    if resolved == home or resolved == Path(resolved.anchor):
        raise OnboardApplyResumeError(f"refusing to remove unsafe checkout: {value}")
    if not path.exists():
        return False
    if not path.is_dir() or path.is_symlink():
        raise OnboardApplyResumeError(f"checkout is not a removable directory: {value}")
    shutil.rmtree(path)
    return True


def _set_missing(parsed: Any, name: str, value: Any) -> None:
    if getattr(parsed, name, None) not in (None, ""):
        return
    if value in (None, ""):
        return
    setattr(parsed, name, value)


def _set_bool_missing(parsed: Any, name: str, value: Any) -> None:
    if getattr(parsed, name, None) is not None:
        return
    if value is None:
        return
    setattr(parsed, name, bool(value))


def _restore_publish_defaults(parsed: Any, value: Any) -> None:
    publish = _mapping(value)
    if not publish:
        return
    _set_missing(parsed, "project_publish_owner", publish.get("owner"))
    _set_missing(parsed, "project_publish_owner_login", publish.get("user_login"))
    _set_missing(parsed, "project_publish_repo_name", publish.get("name"))
    _set_missing(parsed, "project_publish_api_url", publish.get("api_url"))
    _set_bool_missing(parsed, "project_publish_private", publish.get("private"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = [
    "OnboardApplyResumeError",
    "apply_defaults",
    "load_payload",
    "load_snapshot",
    "normalize_run_id",
    "start_over",
    "start_over_checkout_path",
]
