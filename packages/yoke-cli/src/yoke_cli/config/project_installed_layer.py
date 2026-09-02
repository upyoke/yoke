"""What Yoke operating layer a project checkout already carries.

A repository can arrive with a Yoke layer already committed — a clone of a
repo somebody else onboarded, or a checkout whose earlier install was never
removed. The install manifest cannot answer that: it is machine-local and
gitignored, so a fresh clone has none. This module answers it from the layer's
own committed shape, declared once in
:mod:`yoke_contracts.project_contract.installed_layer`.

Onboarding reads the scan twice: the wizard shows it before Review so the
operator can decide to keep or remove the layer, and the review and apply
paths report the same counts so nothing is installed over an uninspected
repository. :mod:`project_installed_layer_removal` performs the removal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_AGENT_DIR_RELS,
    INSTALLED_LAYER_AGENT_PREFIX,
    INSTALLED_LAYER_DIR_RELS,
    INSTALLED_LAYER_FILE_RELS,
    INSTALLED_LAYER_HOOK_COMMAND_TOKEN,
    INSTALLED_LAYER_HOOK_RELS,
    INSTALLED_LAYER_MARKDOWN_RELS,
    read_installed_layer_receipt,
)
from yoke_contracts.project_contract.managed_block import block_span

# What an operator may decide about a layer a repository already carries.
LAYER_DECISION_KEEP = "keep"
LAYER_DECISION_REMOVE = "remove"
LAYER_DECISIONS = (LAYER_DECISION_KEEP, LAYER_DECISION_REMOVE)
LAYER_DECISION_HELP = (
    "what to do with a Yoke operating layer the repository already "
    "carries: remove it before installing, or keep it and install over"
)

# How a group of layer paths is removed, which is also what the inspection
# screen tells the operator would happen to it.
KIND_DIRECTORY = "directory"
KIND_ADAPTERS = "adapters"
KIND_FILE = "file"
KIND_MARKDOWN_BLOCK = "markdown-block"
KIND_HOOK_ENTRIES = "hook-entries"


@dataclass(frozen=True)
class LayerGroup:
    """One place a checkout carries the layer, and how much of it is there."""

    rel: str
    kind: str
    file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {"rel": self.rel, "kind": self.kind, "file_count": self.file_count}


@dataclass(frozen=True)
class InstalledLayerScan:
    """Every layer group one checkout carries, plus its release provenance."""

    root: Path
    groups: tuple[LayerGroup, ...] = ()
    source_engine_release: str = ""

    @property
    def present(self) -> bool:
        return bool(self.groups)

    @property
    def file_count(self) -> int:
        return sum(group.file_count for group in self.groups)

    def as_dict(self) -> dict[str, Any]:
        """The scan as plain data, for the plan and the review screen."""
        return {
            "checkout": str(self.root),
            "present": self.present,
            "file_count": self.file_count,
            "source_engine_release": self.source_engine_release,
            "groups": [group.as_dict() for group in self.groups],
        }


def scan(root: str | Path) -> InstalledLayerScan:
    """Report the Yoke operating layer ``root`` already carries.

    A missing folder, or one with no layer at all, scans to an empty result —
    that is the clean-repository answer, not a failure.
    """
    checkout = Path(str(root)).expanduser()
    if not checkout.is_dir():
        return InstalledLayerScan(checkout)
    groups: list[LayerGroup] = []
    for rel in INSTALLED_LAYER_DIR_RELS:
        count = _file_count(checkout / rel)
        if count:
            groups.append(LayerGroup(rel, KIND_DIRECTORY, count))
    for rel in INSTALLED_LAYER_AGENT_DIR_RELS:
        count = len(list(_adapter_paths(checkout / rel)))
        if count:
            groups.append(LayerGroup(rel, KIND_ADAPTERS, count))
    for rel in INSTALLED_LAYER_FILE_RELS:
        if (checkout / rel).is_file():
            groups.append(LayerGroup(rel, KIND_FILE, 1))
    for rel in INSTALLED_LAYER_MARKDOWN_RELS:
        if _has_managed_block(checkout / rel):
            groups.append(LayerGroup(rel, KIND_MARKDOWN_BLOCK, 1))
    for rel in INSTALLED_LAYER_HOOK_RELS:
        count = len(hook_entry_locations(checkout / rel))
        if count:
            groups.append(LayerGroup(rel, KIND_HOOK_ENTRIES, count))
    receipt = read_installed_layer_receipt(checkout) if groups else None
    release = (
        receipt.source_engine_release
        if receipt is not None and receipt.project_root == checkout.resolve()
        else ""
    )
    return InstalledLayerScan(checkout, tuple(groups), release)


def summarize(root: str | Path) -> dict[str, Any]:
    """The scan of ``root`` as plain data."""
    return scan(root).as_dict()


def adapter_paths(directory: Path) -> list[Path]:
    """The Yoke agent adapters inside one shared harness agents directory."""
    return sorted(_adapter_paths(directory))


def hook_entry_locations(path: Path) -> list[tuple[str, int]]:
    """``(event, index)`` of every Yoke hook entry in one settings file.

    Indices are read in file order, so a caller removing entries must apply
    them from the highest index down.
    """
    payload = _read_json(path)
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        return []
    found: list[tuple[str, int]] = []
    for event in sorted(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if _is_yoke_hook_entry(entry):
                found.append((event, index))
    return found


def _file_count(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.rglob("*") if path.is_file())


def _adapter_paths(directory: Path) -> Iterable[Path]:
    if not directory.is_dir():
        return ()
    return (
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.startswith(INSTALLED_LAYER_AGENT_PREFIX)
    )


def _has_managed_block(path: Path) -> bool:
    try:
        return block_span(path.read_text(encoding="utf-8")) is not None
    except (OSError, UnicodeDecodeError):
        return False


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _is_yoke_hook_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    commands = [entry.get("command")]
    for hook in entry.get("hooks") or []:
        if isinstance(hook, dict):
            commands.append(hook.get("command"))
    return any(
        isinstance(command, str)
        and INSTALLED_LAYER_HOOK_COMMAND_TOKEN in command
        for command in commands
    )


__all__ = [
    "InstalledLayerScan",
    "KIND_ADAPTERS",
    "KIND_DIRECTORY",
    "KIND_FILE",
    "KIND_HOOK_ENTRIES",
    "KIND_MARKDOWN_BLOCK",
    "LAYER_DECISIONS",
    "LAYER_DECISION_HELP",
    "LAYER_DECISION_KEEP",
    "LAYER_DECISION_REMOVE",
    "LayerGroup",
    "adapter_paths",
    "hook_entry_locations",
    "scan",
    "summarize",
]
