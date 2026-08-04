"""Git-only resolution of an item branch's authored-file scope."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from yoke_contracts.project_contract.file_line_policy import item_base_config_key


@dataclass(frozen=True)
class FileLineGitScope:
    integration_target: str
    item_base_sha: str
    own_paths: tuple[str, ...]
    inherited_paths: tuple[str, ...]
    configured_item_base: bool


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _paths(repo_root: Path, *refs: str) -> tuple[str, ...]:
    output = _git(
        repo_root, "diff", "--name-only", "--diff-filter=ACMR", *refs,
    )
    return tuple(path for path in output.splitlines() if path)


def resolve_file_line_git_scope(
    repo_root: Path, integration_target: str,
) -> FileLineGitScope:
    """Resolve own delta from the recorded item base, never moving main."""
    branch = _git(repo_root, "branch", "--show-current")
    configured = ""
    if branch:
        result = subprocess.run(
            [
                "git", "-C", str(repo_root), "config", "--get",
                item_base_config_key(branch),
            ],
            capture_output=True,
            text=True,
            errors="replace",
        )
        configured = result.stdout.strip() if result.returncode == 0 else ""
    if configured:
        _git(repo_root, "rev-parse", "--verify", f"{configured}^{{commit}}")
        item_base = configured
    else:
        item_base = _git(repo_root, "merge-base", "HEAD", integration_target)
    own_paths = _paths(repo_root, item_base)
    inherited_paths = tuple(
        path for path in _paths(repo_root, integration_target, item_base)
        if path not in set(own_paths)
    )
    return FileLineGitScope(
        integration_target=integration_target,
        item_base_sha=item_base,
        own_paths=own_paths,
        inherited_paths=inherited_paths,
        configured_item_base=bool(configured),
    )


__all__ = ["FileLineGitScope", "resolve_file_line_git_scope"]
