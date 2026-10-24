"""Setup publication facts retained by the private durable apply report."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterator, Mapping

from yoke_contracts import terminal_detached_process

_ACTIVE: ContextVar[Any] = ContextVar("setup_report_writer", default=None)


@contextmanager
def recording(writer: Any) -> Iterator[None]:
    token = _ACTIVE.set(writer)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def _git(root: Path, *args: str):
    return terminal_detached_process.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def record_destination(root: Path, github_repo: str) -> None:
    """Save the actual destination as soon as remote choreography succeeds."""
    writer = _ACTIVE.get()
    if writer is None or not github_repo:
        return
    checkout = writer.payload.get("checkout_path")
    if checkout and Path(checkout).expanduser().resolve() == root.resolve():
        writer.payload["target_github_repo"] = github_repo
        writer.write()


def checkout_binding(root: Path, branch: str) -> dict[str, Any]:
    """Bind proof to this physical checkout, project, source and branch."""
    root = root.resolve()
    git_dir = _git(root, "rev-parse", "--absolute-git-dir")
    if git_dir.returncode:
        return {}
    try:
        manifest = json.loads((root / ".yoke/install-manifest.json").read_text())
        project_id = manifest["project_id"]
        if type(project_id) is not int or project_id <= 0:
            return {}
        directory = Path(git_dir.stdout.strip()).stat()
        checkout = root.stat()
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    source = _git(root, "config", "--get", "remote.origin.url").stdout.strip()
    return {
        "checkout": str(root),
        "device": checkout.st_dev,
        "inode": checkout.st_ino,
        "git_device": directory.st_dev,
        "git_inode": directory.st_ino,
        "project_id": project_id,
        "branch": branch,
        "source_digest": hashlib.sha256(source.encode()).hexdigest(),
    }


def record_created(root: Path, commit: Mapping[str, Any], *, writer=None) -> None:
    """Persist only the commit creation result, never publication's current HEAD."""
    writer = writer or _ACTIVE.get()
    sha = str(commit.get("sha") or "")
    if (
        writer is None
        or commit.get("status") != "created"
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        return
    branch = _git(root, "branch", "--show-current").stdout.strip()
    binding = checkout_binding(root, branch)
    if not binding or _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode:
        return
    receipt = {"binding": binding, "sha": sha}
    receipts = writer.payload.setdefault("created_commits", [])
    if receipt not in receipts:
        receipts.append(receipt)
        writer.write()


def verified_commits(root: Path, branch: str) -> tuple[str, ...]:
    """Read private setup receipts; unreceipted and replaced checkouts stay unproven."""
    from yoke_cli.config import onboard_apply_report, onboard_checklist

    binding = checkout_binding(root, branch)
    if not binding:
        return ()
    found: set[str] = set()
    active = _ACTIVE.get()
    reports = onboard_checklist.runs_dir() / onboard_apply_report.REPORTS_DIR_NAME
    for path in reports.glob("*.json"):
        try:
            metadata = path.lstat()
            if (
                path.is_symlink()
                or metadata.st_mode & 0o077
                or metadata.st_size > 2_000_000
            ):
                continue
            payload = json.loads(path.read_text())
            if (
                not isinstance(payload, dict)
                or payload.get("schema") != onboard_apply_report.SCHEMA_NAME
            ):
                continue
            if active and any(
                payload.get(key) != active.payload.get(key)
                for key in ("config_path", "env", "api_url")
            ):
                continue
            for receipt in payload.get("created_commits", []):
                if not isinstance(receipt, dict) or receipt.get("binding") != binding:
                    continue
                sha = str(receipt.get("sha") or "")
                if (
                    re.fullmatch(r"[0-9a-f]{40}", sha)
                    and not _git(
                        root, "merge-base", "--is-ancestor", sha, "HEAD"
                    ).returncode
                ):
                    found.add(sha)
        except (OSError, ValueError, TypeError):
            continue
    return tuple(sorted(found))
