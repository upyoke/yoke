"""Support helpers for project onboarding workflows."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from yoke_cli.config import machine_config
from yoke_cli.config import project_onboarding_handoff
from yoke_cli.config import project_worktrees_ignore
from yoke_cli.config.project_github_adoption import (
    with_github_adoption_report,
)
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef

PLAN = [
    "project.upsert",
    "project.capabilities.configure",
    "project.checkout.register",
    "project.install",
]


class ProjectOnboardError(RuntimeError):
    """Project onboarding cannot proceed."""


class ProjectDispatchError(ProjectOnboardError):
    """A project onboarding dispatcher call returned an error envelope."""

    def __init__(self, function_id: str, code: str, message: str) -> None:
        self.function_id = function_id
        self.code = code
        super().__init__(f"{function_id} failed: {message}")


def dry_run_report(
    *,
    operation: str = "onboard.project",
    repo_root: str | Path,
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    default_branch: str,
    public_item_prefix: str,
    github_adoption: Mapping[str, Any] | None = None,
    checkout_mode: str = "existing-local",
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    report = {
        "operation": operation,
        "applied": False,
        "project": _project_preview(
            slug, name, org, github_repo, default_branch, public_item_prefix,
        ),
        "checkout": {"path": str(root), "mode": checkout_mode},
        "worktrees_ignore": project_worktrees_ignore.report(root, apply=False),
        "plan": list(PLAN),
    }
    return with_github_adoption_report(
        report,
        operation=operation,
        root=root,
        project=report["project"],
        github_adoption=github_adoption,
    )


def project_api_payload(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}

def project_dry_run(
    operation: str,
    root: Path,
    payload: Mapping[str, Any],
    mode: str,
    github_adoption: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "operation": operation,
        "applied": False,
        "project": dict(payload),
        "checkout": {"path": str(root), "mode": mode},
        "worktrees_ignore": project_worktrees_ignore.report(root, apply=False),
        "plan": list(PLAN),
    }
    return with_github_adoption_report(
        report,
        operation=operation,
        root=root,
        project=payload,
        github_adoption=github_adoption,
    )


def applied_report(
    operation: str,
    root: Path,
    project: Mapping[str, Any],
    install: Mapping[str, Any],
    api_result: Mapping[str, Any],
    github_adoption: Mapping[str, Any] | None = None,
    *,
    config_path: str | Path | None = None,
    secret_result: Mapping[str, Any] | None = None,
    clone_outcome: Any | None = None,
) -> dict[str, Any]:
    project_id = int(project["id"])
    worktrees_ignore = project_worktrees_ignore.report(root, apply=True)
    report = {
        "operation": operation,
        "applied": True,
        "project": project_result(project),
        "checkout": {
            "path": str(root),
            "project_id": project_id,
            "registered": True,
        },
        "install": dict(install),
        "worktrees_ignore": worktrees_ignore,
        "capabilities": capabilities_report(api_result, secret_result),
    }
    resume = clone_resume_report(clone_outcome)
    if resume is not None:
        report["clone_resume"] = resume
    report["handoff"] = project_onboarding_handoff.create_handoff(
        operation=operation,
        root=root,
        project=project,
        install=install,
        github_adoption=github_adoption,
        config_path=config_path,
        dispatch_fn=dispatch,
    )
    return with_github_adoption_report(
        report,
        operation=operation,
        root=root,
        project=project,
        github_adoption=github_adoption,
    )


def clone_resume_report(clone_outcome: Any | None) -> dict[str, bool] | None:
    """Project a clone apply's resume flags onto the report, or ``None``.

    Only attached when the clone apply actually reused a prior run's work, so a
    fresh run's report stays byte-identical — the resume-aware report lines key
    off the presence of this block. Read duck-typed (``getattr``) so the support
    layer does not import the clone module (which imports this one).
    """
    if clone_outcome is None:
        return None
    flags = {
        "clone_reused": bool(getattr(clone_outcome, "clone_reused", False)),
        "repo_reused": bool(getattr(clone_outcome, "repo_reused", False)),
        "origin_rehomed": bool(getattr(clone_outcome, "origin_rehomed", False)),
    }
    if not any(flags.values()):
        return None
    return flags


def capabilities_report(
    api_result: Mapping[str, Any],
    secret_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    capabilities = {
        str(cap_type): dict(value)
        for cap_type, value in dict(api_result.get("capabilities") or {}).items()
        if isinstance(value, Mapping)
    }
    if secret_result:
        cap_type = str(secret_result.get("cap_type") or "")
        key = str(secret_result.get("key") or "")
        if cap_type and key:
            capability = dict(capabilities.get(cap_type) or {})
            secret_refs = [
                str(ref)
                for ref in capability.get("secret_refs", [])
            ]
            if key not in secret_refs:
                secret_refs.append(key)
            capability["secret_refs"] = secret_refs
            capabilities[cap_type] = capability
    return capabilities


def project_result(project: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(project["id"]),
        "slug": project.get("slug"),
        "name": project.get("name"),
        "github_repo": project.get("github_repo"),
        "default_branch": project.get("default_branch"),
        "public_item_prefix": project.get("public_item_prefix"),
    }


def dispatch(
    function_id: str,
    payload: Mapping[str, Any],
    config_path: str | Path | None,
) -> Mapping[str, Any]:
    with machine_config_path(config_path):
        response = call_dispatcher(
            function_id=function_id,
            target=TargetRef(kind="global"),
            payload=dict(payload),
        )
    if not response.success:
        message = response.error.message if response.error else "unknown error"
        code = response.error.code if response.error else "unknown_error"
        raise ProjectDispatchError(function_id, code, message)
    return response.result or {}


@contextlib.contextmanager
def machine_config_path(config_path: str | Path | None) -> Iterator[None]:
    if config_path is None:
        yield
        return
    old = os.environ.get(machine_config.CONFIG_FILE_ENV)
    os.environ[machine_config.CONFIG_FILE_ENV] = str(config_path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(machine_config.CONFIG_FILE_ENV, None)
        else:
            os.environ[machine_config.CONFIG_FILE_ENV] = old


def project_from_result(result: Mapping[str, Any]) -> Mapping[str, Any]:
    project = result.get("project")
    if not isinstance(project, Mapping) or not project.get("id"):
        row = result.get("row")
        if isinstance(row, Mapping) and row.get("id"):
            return row
        raise ProjectOnboardError("project response did not include project.id")
    return project


def github_token(
    *,
    token: str | None,
    token_file: str | Path | None,
    token_stdin_value: str | None,
) -> tuple[str | None, str | None]:
    sources = [bool(token), bool(token_file), token_stdin_value is not None]
    if sum(1 for source in sources if source) > 1:
        raise ProjectOnboardError("Project GitHub credential inputs are mutually exclusive")
    if any(sources):
        raise ProjectOnboardError(
            "Project-supplied GitHub credentials are no longer supported; use a "
            "GitHub App repo binding or backlog-only mode."
        )
    return None, None


def ensure_new_checkout(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ProjectOnboardError(f"checkout already exists and is not empty: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)


def _project_preview(
    slug: str,
    name: str,
    org: str | None,
    github_repo: str | None,
    default_branch: str,
    public_item_prefix: str,
) -> dict[str, str | None]:
    values = {
        "slug": slug,
        "name": name,
        "org": org,
        "github_repo": github_repo,
        "default_branch": default_branch,
        "public_item_prefix": public_item_prefix,
    }
    return {key: value for key, value in values.items() if value is not None}
