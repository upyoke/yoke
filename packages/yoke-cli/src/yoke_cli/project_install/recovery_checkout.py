"""Exact planned bytes that authorize resuming a dirty interrupted checkout."""

from __future__ import annotations

import json
from pathlib import Path
import re
import stat
from typing import Any

from yoke_cli.project_install import (
    checkout_gate,
    cursor_permissions,
    managed_markdown,
    settings_permissions,
    settings_status_line,
    skill_discovery,
)
from yoke_cli.project_install.file_line_managed_exceptions import (
    _existing_text,
    managed_markdown_paths,
    planned_config_text,
)
from yoke_cli.project_install.files import sha256_text
from yoke_contracts.project_contract.file_line_policy import PROJECT_CONFIG_REL
from yoke_contracts.project_contract.install_bundle import SKILL_DISCOVERY_LINKS


def state(path: Path) -> str:
    """Name one path's state: absent, a link by its resolved target, or content."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return "absent"
    if skill_discovery.is_link_entry(info):
        return "link:" + str(path.resolve())
    if stat.S_ISDIR(info.st_mode):
        return "directory"
    return sha256_text(path.read_bytes().decode("utf-8"))


def states(path: Path) -> set[str]:
    """Return every safe state that proves the current installer-owned path."""
    return {state(path)}


def in_interrupted_copy(root: Path, rel: str) -> bool:
    """Whether *rel* is inside a killed install's own local discovery copy."""
    return any(
        (rel.rstrip("/") == entry or rel.startswith(entry + "/"))
        and skill_discovery.entry_state(root, entry) == skill_discovery.COPIED
        for entry in SKILL_DISCOVERY_LINKS
    )


def own_dirty_paths(root: Path) -> list[str]:
    """Dirty paths a recovery must commit: local discovery copies stay untracked."""
    from yoke_cli.project_install.install_recovery import PENDING_REL

    paths = [
        checkout_gate._porcelain_path(line) for line in checkout_gate.porcelain(root)
    ]
    return [
        rel
        for rel in paths
        if rel != PENDING_REL and not in_interrupted_copy(root, rel)
    ]


def remove_staging_leftovers(root: Path, expected: dict[str, Any]) -> None:
    """Delete untracked temp files a killed atomic write left beside planned paths."""
    for rel in expected:
        target = root / rel
        pattern = re.compile(re.escape("." + target.name) + r"[a-z0-9_]{8}")
        if not target.parent.is_dir():
            continue
        for leftover in target.parent.iterdir():
            if not pattern.fullmatch(leftover.name) or not leftover.is_file():
                continue
            if leftover.is_symlink():
                continue
            tracked = checkout_gate.run_git(
                root, "ls-files", "--", str(leftover.relative_to(root))
            )
            if tracked.returncode == 0 and not tracked.stdout.strip():
                leftover.unlink()


def _add_line_exception_states(root: Path, bundle: dict[str, Any], add) -> None:
    """Plan the exemptions the install appends to a seeded or existing config."""
    managed = managed_markdown_paths(bundle)
    sources = [
        entry["content"]
        for entry in bundle.get("project_contract_files") or []
        if entry["path"] == PROJECT_CONFIG_REL
    ]
    # Read as the installer reads it, so the planned bytes match what it writes.
    sources.append(_existing_text(root / PROJECT_CONFIG_REL))
    for source in sources:
        add(PROJECT_CONFIG_REL, planned_config_text(source, managed))


def plan(
    root: Path, bundle: dict[str, Any], prior: dict[str, Any], preflight: dict[str, Any]
) -> dict[str, list[str]]:
    """Use the existing pure planners, including intermediate settings writes."""
    expected: dict[str, set[str]] = {}

    def add(rel: str, content: str | None):
        states = expected.setdefault(rel, {state(root / rel)})
        states.add("absent" if content is None else sha256_text(content))

    def json_state(rel: str, value: Any):
        add(rel, json.dumps(value, indent=2) + "\n")

    expected[".yoke/install-manifest.json"] = {
        state(root / ".yoke/install-manifest.json")
    }
    for rel in prior.get("files") or {}:
        expected.setdefault(rel, {state(root / rel)})
    for entry in bundle["files"]:
        add(entry["path"], entry["content"])
    for entry in bundle.get("project_contract_files") or []:
        add(entry["path"], entry["content"])
    for entry in bundle.get("strategy_files") or []:
        add(entry["path"], entry["content"])
    _add_line_exception_states(root, bundle, add)
    for rel in preflight["install_recovery"]["removed_paths"]:
        add(rel, None)
    for rel, destination in SKILL_DISCOVERY_LINKS.items():
        linked = "link:" + str(((root / rel).parent / destination).resolve())
        expected.setdefault(rel, {state(root / rel)}).update({"absent", linked})
    for rel, planned in preflight["hook_plans"].items():
        json_state(rel, planned["payload"])
        if planned["deleted_file"]:
            add(rel, None)
    claude = preflight["hook_plans"].get(".claude/settings.json")
    payload = claude["payload"] if claude else None
    permissions = bundle.get("claude_settings_permissions")
    if permissions:
        payload, _ = settings_permissions._plan(
            payload, permissions, prior.get("settings_permissions")
        )
        json_state(".claude/settings.json", payload)
    status = bundle.get(settings_status_line.MANAGED_STATUS_LINE_KEY)
    if status and (
        settings_status_line._seeds(payload)
        or (prior.get("settings_status_line") or {}).get("seeded")
    ):
        payload = dict(payload or {})
        payload["statusLine"] = settings_status_line._validate(status)
        json_state(".claude/settings.json", payload)
    for region, _, payload, _ in cursor_permissions._region_plans(root):
        json_state(region.rel, payload)
    for entry in (
        managed_markdown.resolve_targets(bundle.get("managed_markdown"))
        if bundle.get("managed_markdown")
        else []
    ):
        _, text = managed_markdown.plan_markdown_block(
            managed_markdown._read_current(root / entry["path"]), entry["content"]
        )
        add(entry["path"], text)
    from yoke_cli.config.project_worktrees_ignore import planned_text

    ignore = root / ".gitignore"
    text = ignore.read_text(encoding="utf-8") if ignore.is_file() else ""
    for rel in SKILL_DISCOVERY_LINKS:
        entry = skill_discovery.ignore_entry(rel)
        planned = planned_text(text, entry)
        if planned != text:
            add(".gitignore", planned)
            text = planned
    for entry in bundle.get("project_contract_files") or []:
        if entry["path"] != ".yoke/.gitignore":
            continue
        target = root / entry["path"]
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        present = {line.strip() for line in text.splitlines() if line.strip()}
        missing = [
            line
            for line in entry["content"].splitlines()
            if line.strip()
            and not line.lstrip().startswith("#")
            and line not in present
        ]
        if missing:
            add(
                entry["path"],
                text
                + ("\n" if text and not text.endswith("\n") else "")
                + "\n".join(missing)
                + "\n",
            )
    return {rel: sorted(states) for rel, states in expected.items()}
