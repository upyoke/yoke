"""Validation and commit resolution for pinned deployment product sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Sequence


class DeployProductSourceError(ValueError):
    """A deployment product checkout or pin is unsafe to use."""


@dataclass(frozen=True)
class DeployProductSource:
    repo_path: str
    commit: str


def validate_itemless_product_source(
    repo_path: str,
    image_tag: str,
    member_items: Sequence[str],
) -> DeployProductSource | None:
    """Validate an explicit product source and refuse it for item-bound runs."""
    selected = str(repo_path or "").strip()
    if not selected:
        return None
    if member_items:
        raise DeployProductSourceError(
            "--product-repo-path is only valid for itemless environment deploys"
        )
    return validate_product_source(selected, image_tag)


def validate_product_source(repo_path: str | Path, image_tag: str) -> DeployProductSource:
    """Require a clean Git top-level whose HEAD is the explicit image pin."""
    path = Path(repo_path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise DeployProductSourceError(f"product repo path is not a directory: {path}")
    top_level = Path(_git(path, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if top_level != path:
        raise DeployProductSourceError(
            f"product repo path must be the Git worktree top-level: {top_level}"
        )
    dirty = _git(path, "status", "--porcelain=v1", "--untracked-files=normal")
    if dirty:
        raise DeployProductSourceError(
            "product repo checkout must be clean before a pinned deploy"
        )
    commit = resolve_product_commit(path, image_tag)
    head = _git(path, "rev-parse", "--verify", "HEAD^{commit}")
    if commit != head:
        raise DeployProductSourceError(
            f"image tag resolves to {commit}, but product checkout HEAD is {head}"
        )
    return DeployProductSource(repo_path=str(path), commit=commit)


def resolve_product_commit(repo_path: str | Path, image_tag: str) -> str:
    """Expand an explicit image tag to its full commit in ``repo_path``."""
    selected_tag = str(image_tag or "").strip()
    if not selected_tag:
        raise DeployProductSourceError(
            "--product-repo-path requires an explicit --image-tag"
        )
    if selected_tag.startswith("-"):
        raise DeployProductSourceError("image tag cannot start with '-'")
    return _git(
        Path(repo_path), "rev-parse", "--verify", f"{selected_tag}^{{commit}}"
    )


def _git(repo_path: Path, *args: str) -> str:
    command = ["git", "-C", str(repo_path), *args]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeployProductSourceError(
            f"could not inspect product repo with {' '.join(args)}: {exc}"
        ) from exc
    output = result.stdout.strip()
    if result.returncode != 0:
        detail = result.stderr.strip() or output or f"exit {result.returncode}"
        raise DeployProductSourceError(
            f"product repo git {' '.join(args)} failed: {detail}"
        )
    return output


__all__ = [
    "DeployProductSource",
    "DeployProductSourceError",
    "resolve_product_commit",
    "validate_itemless_product_source",
    "validate_product_source",
]
