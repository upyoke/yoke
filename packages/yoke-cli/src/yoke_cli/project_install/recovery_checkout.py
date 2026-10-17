"""Exact planned bytes that authorize resuming a dirty interrupted checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from yoke_cli.project_install import (
    cursor_permissions,
    managed_markdown,
    settings_permissions,
    settings_status_line,
)
from yoke_cli.project_install.files import sha256_text
from yoke_contracts.project_contract.install_bundle import SKILL_DISCOVERY_LINKS


def state(path: Path) -> str:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    if not path.exists():
        return "absent"
    return sha256_text(path.read_bytes().decode("utf-8"))


def text_digests(content: str) -> set[str]:
    """Return exact and CRLF-normalized hashes for installer recovery proof."""
    return {
        sha256_text(content),
        sha256_text(content.replace("\r\n", "\n")),
    }


def states(path: Path) -> set[str]:
    """Return every safe state that proves the current installer-owned path."""
    if path.is_symlink() or not path.exists():
        return {state(path)}
    return text_digests(path.read_bytes().decode("utf-8"))


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
    for rel in preflight["install_recovery"]["removed_paths"]:
        add(rel, None)
    for rel, destination in SKILL_DISCOVERY_LINKS.items():
        expected.setdefault(
            rel,
            {
                "directory"
                if (root / rel).is_dir() and not (root / rel).is_symlink()
                else state(root / rel)
            },
        )
        expected[rel].add("link:" + destination)
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
    # These two append-only owners expose their canonical entries directly.
    from yoke_cli.config.project_worktrees_ignore import WORKTREES_IGNORE_ENTRY, report

    ignore = root / ".gitignore"
    if not report(root, apply=False)["present"]:
        text = ignore.read_text() if ignore.is_file() else ""
        add(
            ".gitignore",
            text
            + ("\n" if text and not text.endswith("\n") else "")
            + WORKTREES_IGNORE_ENTRY
            + "\n",
        )
    for entry in bundle.get("project_contract_files") or []:
        if entry["path"] != ".yoke/.gitignore":
            continue
        target = root / entry["path"]
        if not target.is_file():
            continue
        text = target.read_text()
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
