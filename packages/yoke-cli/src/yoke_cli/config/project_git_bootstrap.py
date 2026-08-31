"""Init a checkout and optionally create a private GitHub remote.

This is the workhorse behind ``project.git.bootstrap``. Installer create
and existing-folder paths call :func:`prepare_checkout` so git init, the
starter ``.gitignore``, and the initial commit are the same operation an
agent can invoke later — not wizard-only choreography.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import project_checkout_path
from yoke_cli.config import project_git_bootstrap_local as local
from yoke_cli.config import project_git_bootstrap_remote as remote
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config import project_publish_support as pub
from yoke_cli.config.project_onboard_support import ProjectOnboardError
from yoke_cli.config.project_publish_request import PublishRequest
from yoke_contracts.project_git_bootstrap import GIT_BOOTSTRAP_USAGE

DEFAULT_BRANCH = "main"
STARTER_GITIGNORE = local.STARTER_GITIGNORE
prepare_checkout = local.prepare_checkout
refuse_nested_checkout = local.refuse_nested_checkout

_InitFn = Callable[[Path, str], bool]
_PublishFn = Callable[..., dict[str, Any]]
_NeededFn = Callable[[Path, PublishRequest], bool]


@dataclass
class GitBootstrapResult:
    """Receipt for one bootstrap invocation (dry-run or apply)."""

    checkout: str
    dry_run: bool
    initialized: bool = False
    gitignore_written: bool = False
    committed: bool = False
    remote_created: bool = False
    github_repo: str | None = None
    bound: bool = False
    skipped: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "checkout": self.checkout,
            "dry_run": self.dry_run,
            "initialized": self.initialized,
            "gitignore_written": self.gitignore_written,
            "committed": self.committed,
            "remote_created": self.remote_created,
            "github_repo": self.github_repo,
            "bound": self.bound,
            "skipped": list(self.skipped),
            "planned": list(self.planned),
        }
        payload["text"] = render_text(self)
        return payload


def bootstrap_checkout(
    checkout: str | Path,
    *,
    init_repo: bool = True,
    create_remote: bool = True,
    project_slug: str | None = None,
    owner: str | None = None,
    name: str | None = None,
    default_branch: str = DEFAULT_BRANCH,
    apply: bool = False,
    config_path: str | Path | None = None,
    publish: PublishRequest | None = None,
    init_repo_if_needed: _InitFn | None = None,
    create_and_publish: _PublishFn | None = None,
    publish_needed: _NeededFn | None = None,
) -> GitBootstrapResult:
    """Idempotent local init plus optional private GitHub remote + binding."""

    root = project_checkout_path.for_apply(
        checkout, error_type=ProjectOnboardError,
    )
    project_git_prerequisite.require_git_available()
    local.refuse_nested_checkout(root)
    result = GitBootstrapResult(checkout=str(root), dry_run=not apply)
    if not apply:
        _plan(result, root, init_repo, create_remote, owner, name, default_branch)
        return result
    prepared = local.prepare_checkout(
        root,
        default_branch,
        init_repo=init_repo,
        init_repo_if_needed=init_repo_if_needed or pub.init_repo_if_needed,
    )
    result.initialized = bool(prepared["initialized"])
    result.gitignore_written = bool(prepared["gitignore_written"])
    result.committed = bool(prepared["committed"])
    skipped = prepared["skipped"]
    if isinstance(skipped, list):
        result.skipped.extend(str(part) for part in skipped)
    if not create_remote:
        result.skipped.append("create-remote")
        return result
    if pub.has_remote(root):
        result.skipped.append("create-remote")
        result.github_repo = remote.origin_full_name(root)
        if project_slug and result.github_repo:
            result.bound = remote.bind_project(
                project_slug, result.github_repo, config_path,
            )
        return result
    request = publish or remote.publish_request(
        root, owner=owner, name=name, config_path=config_path,
    )
    needed = publish_needed or pub.publish_checkout_needed
    publisher = create_and_publish or pub.create_and_publish
    if not needed(root, request):
        result.skipped.append("create-remote")
        return result
    created = publisher(root, request, default_branch=default_branch)
    result.remote_created = True
    result.github_repo = str(created.get("full_name") or request.full_name)
    if project_slug and result.github_repo:
        result.bound = remote.bind_project(
            project_slug, result.github_repo, config_path,
        )
    return result


def render_text(result: GitBootstrapResult) -> str:
    """One human paragraph for CLI stdout."""

    if result.dry_run:
        actions = result.planned or ["no changes"]
        return "dry-run: " + "; ".join(actions)
    parts = []
    if result.initialized:
        parts.append("initialized git repository")
    if result.gitignore_written:
        parts.append("wrote starter .gitignore")
    if result.committed:
        parts.append("created initial commit")
    if result.remote_created and result.github_repo:
        parts.append(f"created private GitHub repository {result.github_repo}")
    if result.bound:
        parts.append("recorded GitHub binding")
    if result.skipped:
        parts.append("skipped: " + ", ".join(result.skipped))
    return "; ".join(parts) or "already bootstrapped"


def _plan(
    result: GitBootstrapResult,
    root: Path,
    init_repo: bool,
    create_remote: bool,
    owner: str | None,
    name: str | None,
    default_branch: str,
) -> None:
    if init_repo and not pub.is_git_repo(root):
        result.planned.append(f"git init --initial-branch {default_branch}")
        result.planned.append("write starter .gitignore")
        result.planned.append("create initial commit")
    elif not init_repo:
        result.planned.append("skip init")
    else:
        result.planned.append("leave existing git repository unchanged")
    if not create_remote:
        result.planned.append("skip remote creation")
        return
    if pub.has_remote(root):
        result.planned.append("leave existing origin unchanged")
        return
    label = f"{owner or '<owner>'}/{name or root.name}"
    result.planned.append(f"create private GitHub repository {label} and push")


__all__ = [
    "DEFAULT_BRANCH",
    "GIT_BOOTSTRAP_USAGE",
    "GitBootstrapResult",
    "STARTER_GITIGNORE",
    "bootstrap_checkout",
    "prepare_checkout",
    "refuse_nested_checkout",
    "render_text",
]
