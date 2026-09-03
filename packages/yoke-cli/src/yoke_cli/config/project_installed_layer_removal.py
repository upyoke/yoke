"""Remove a Yoke operating layer a project checkout arrived with.

``yoke project uninstall`` removes a layer this machine installed, which it
reads from the machine-local install manifest. A repository that arrived with
a layer already committed has no such manifest, so this module removes what
:mod:`project_installed_layer` scanned instead: the layer's own directories
and adapters go, and the regions Yoke merged into files a project co-owns —
the managed Markdown block, the harness hook entries — are stripped while the
rest of those files stays untouched.

The removal commits itself in a git checkout. Onboarding installs into the
folder immediately afterwards, and an install that begins on a tree carrying
uncommitted deletions leaves the operator with a dirty repository whose
history never records what was taken out.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yoke_contracts.project_contract.managed_block import block_span
from yoke_cli.config import project_installed_layer as layer
from yoke_cli.config.project_git_transport import non_interactive_git_env
from yoke_cli.project_install.checkout_gate import commit_identity_args

REMOVAL_COMMIT_MESSAGE = "Remove the existing Yoke operating layer"


@dataclass
class LayerRemovalReport:
    """What the removal took out of the checkout, and whether it committed."""

    removed_paths: list[str] = field(default_factory=list)
    committed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "removed_paths": list(self.removed_paths),
            "removed_path_count": len(self.removed_paths),
            "committed": self.committed,
        }


def remove(root: str | Path) -> dict[str, Any]:
    """Remove the layer ``root`` carries; report what was taken out.

    Removing nothing is a valid outcome — a checkout with no layer reports an
    empty removal rather than failing.
    """
    checkout = Path(str(root)).expanduser()
    scan = layer.scan(checkout)
    report = LayerRemovalReport()
    for group in scan.groups:
        target = checkout / group.rel
        if group.kind == layer.KIND_DIRECTORY:
            _remove_tree(target, group.rel, report)
        elif group.kind == layer.KIND_ADAPTERS:
            for adapter in layer.adapter_paths(target):
                _remove_file(adapter, f"{group.rel}/{adapter.name}", report)
        elif group.kind == layer.KIND_FILE:
            _remove_file(target, group.rel, report)
        elif group.kind == layer.KIND_MARKDOWN_BLOCK:
            _strip_managed_block(target, group.rel, report)
        elif group.kind == layer.KIND_HOOK_ENTRIES:
            _strip_hook_entries(target, group.rel, report)
    _prune_empty_parents(checkout, report.removed_paths)
    report.committed = _commit_removal(checkout, report.removed_paths)
    return report.as_dict()


def _remove_tree(target: Path, rel: str, report: LayerRemovalReport) -> None:
    if not target.is_dir():
        return
    shutil.rmtree(target)
    report.removed_paths.append(rel)


def _remove_file(target: Path, rel: str, report: LayerRemovalReport) -> None:
    if not target.is_file():
        return
    target.unlink()
    report.removed_paths.append(rel)


def _strip_managed_block(target: Path, rel: str, report: LayerRemovalReport) -> None:
    """Cut the managed block out, deleting a file the block was all of."""
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    span = block_span(text)
    if span is None:
        return
    start, end = span
    remaining = (text[:start] + text[end:]).strip()
    if remaining:
        target.write_text(remaining + "\n", encoding="utf-8")
    else:
        target.unlink()
    report.removed_paths.append(rel)


def _strip_hook_entries(target: Path, rel: str, report: LayerRemovalReport) -> None:
    """Drop Yoke's hook entries, leaving every other entry where it was."""
    locations = layer.hook_entry_locations(target)
    if not locations:
        return
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, index in reversed(locations):
        entries = hooks.get(event)
        if isinstance(entries, list) and index < len(entries):
            del entries[index]
    for event in [name for name, entries in hooks.items() if not entries]:
        del hooks[event]
    if not hooks:
        del payload["hooks"]
    if payload:
        # Key order is the project's, not ours: this file is theirs and only
        # the entries Yoke merged in are being taken back out.
        target.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    else:
        target.unlink()
    report.removed_paths.append(rel)


def _prune_empty_parents(checkout: Path, removed_paths: list[str]) -> None:
    """Drop directories the removal emptied, never the checkout itself."""
    for rel in sorted(removed_paths, key=lambda value: value.count("/"), reverse=True):
        parent = (checkout / rel).parent
        while parent != checkout and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _commit_removal(checkout: Path, removed_paths: list[str]) -> bool:
    """Commit the removal, or report that there was nothing git could record."""
    if not removed_paths or not (checkout / ".git").exists():
        return False
    if _git(checkout, "add", "-A", "--", *removed_paths).returncode != 0:
        return False
    if _git(checkout, "diff", "--cached", "--quiet").returncode == 0:
        return False
    committed = _git(
        checkout,
        *commit_identity_args(checkout),
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--no-verify",
        "-m",
        REMOVAL_COMMIT_MESSAGE,
    )
    return committed.returncode == 0


def _git(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True,
        text=True,
        env=non_interactive_git_env(),
        check=False,
    )


__all__ = ["REMOVAL_COMMIT_MESSAGE", "LayerRemovalReport", "remove"]
