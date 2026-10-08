"""Plan baseline-owned instruction retirement and check native Claude loading."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    sha256_text,
)
from yoke_contracts.project_contract.managed_block import block_span
from yoke_contracts.harness_cli_manifest import CLAUDE_AGENTS_MINIMUM_VERSION

RETIRED_INSTRUCTION_PATHS = ("CLAUDE.md", "CODEX.md", "CURSOR.md")


def retirement_plan(root: Path, prior: dict[str, Any]) -> dict[str, str | None]:
    """Only a matching prior block digest authorizes retiring that block."""
    plans = {}
    records = prior.get("managed_markdown") or {}
    for rel in RETIRED_INSTRUCTION_PATHS:
        target = root / rel
        assert_resolved_targets_within(root, [rel], context="instruction retirement")
        if target.is_symlink():
            # A project-owned link already reads the canonical bytes once.
            # Never strip its target's managed block.
            continue
        if not target.is_file():
            continue
        current = target.read_bytes().decode("utf-8")
        span = block_span(current)
        if span is None:
            continue
        start, end = span
        record = records.get(rel) or {}
        if record.get("block_sha") != sha256_text(
            current[start:end].replace("\r\n", "\n")
        ):
            raise ProjectInstallError(
                f"instruction_ownership_ambiguous: {rel} has a modified Yoke "
                "block or no prior baseline. Preserved all files; compare "
                "with the original install manifest, save your edits outside "
                "the managed block, then rerun refresh with that lineage."
            )
        remainder = current[:start] + current[end:]
        plans[rel] = (
            None if record.get("file_created") and not remainder.strip() else remainder
        )
    return plans


def apply_retirement(root: Path, plans: dict[str, str | None]) -> list[str]:
    for rel, content in plans.items():
        target = root / rel
        if content is None:
            target.unlink()
        else:
            target.write_bytes(content.encode("utf-8"))
    return list(plans)


def _settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            for key in ("enabledPlugins", "pluginConfigs"):
                if key in value and not isinstance(value[key], dict):
                    raise ValueError(f"{key} must be an object")
            for config in (value.get("pluginConfigs") or {}).values():
                if not isinstance(config, dict) or not isinstance(
                    config.get("options", {}), dict
                ):
                    raise ValueError("plugin options must be objects")
            exclusions = value.get("claudeMdExcludes", [])
            if not isinstance(exclusions, list) or not all(
                isinstance(p, str) for p in exclusions
            ):
                raise ValueError("claudeMdExcludes must be a string array")
            return value
    except (OSError, UnicodeError, ValueError):
        pass
    raise ProjectInstallError(
        f"instruction_configuration_unreadable: {path}; repair its JSON "
        "before project refresh (contents were not printed)"
    )


def assert_claude_loading(
    root: Path,
    plans: dict[str, str | None],
    *,
    settings: dict[str, Any],
) -> None:
    """Check projected instruction files, keeping user-specific prose intact."""
    plugins = settings.get("enabledPlugins") or {}
    configs = settings.get("pluginConfigs") or {}
    plugin_ids = ("agents-md@builtin", "cc-plugin-agents-md@builtin")
    if any(plugins.get(key) is False for key in plugin_ids):
        _loading_refusal("the built-in AGENTS.md plugin is disabled")
    configured = {
        (configs.get(key) or {}).get("options", {}).get("instructionFiles")
        for key in plugin_ids
    } - {None}
    if len(configured) > 1:
        _loading_refusal("the built-in plugin has conflicting configuration entries")
    mode = next(iter(configured), "claude-md-or-agents-md")
    if mode not in {"claude-md-or-agents-md", "claude-md-and-agents-md"}:
        _loading_refusal(f"Project instructions is {mode!r}")
    for pattern in settings.get("claudeMdExcludes") or []:
        if fnmatch.fnmatch(str(root / "AGENTS.md"), pattern) or fnmatch.fnmatch(
            "AGENTS.md", pattern
        ):
            _loading_refusal("claudeMdExcludes excludes the canonical AGENTS.md")
    if mode == "claude-md-and-agents-md":
        return
    for directory in (root, *root.parents):
        for rel in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            path = directory / rel
            if directory == root and rel in plans and plans[rel] is None:
                continue
            if path.is_file():
                if path.resolve() == (root / "AGENTS.md").resolve():
                    continue
                _loading_refusal(f"{path} suppresses native AGENTS.md loading")


def _loading_refusal(detail: str) -> None:
    raise ProjectInstallError(
        f"canonical_instructions_not_loaded: {detail}. Preserved project content. "
        "Upgrade Claude Code to >=2.1.281, enable the built-in AGENTS.md plugin "
        "in /plugin, and set Project instructions to claude-md-and-agents-md "
        "in /config (user/managed/--settings, never project settings). Remove "
        "exclusions for AGENTS.md and start a new session; verify its path in "
        "/memory. No CLAUDE.md fallback is installed."
    )


def preflight(root: Path, prior: dict[str, Any]) -> dict[str, str | None]:
    plans = retirement_plan(root, prior)
    if (root / "AGENTS.override.md").is_file():
        raise ProjectInstallError(
            "canonical_instructions_not_loaded: AGENTS.override.md suppresses "
            "Codex's canonical AGENTS.md. Preserve its project content in "
            "AGENTS.md outside the Yoke block, then move the override outside "
            "native instruction discovery and rerun refresh."
        )
    executable = shutil.which("claude")
    if executable is None:
        return plans
    try:
        probe = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", probe.stdout)
        observed = (
            tuple(map(int, match.groups())) if match and probe.returncode == 0 else ()
        )
    except (OSError, subprocess.TimeoutExpired):
        observed = ()
    if observed < tuple(map(int, CLAUDE_AGENTS_MINIMUM_VERSION.split("."))):
        raise ProjectInstallError(
            f"instruction_runtime_unsupported: Claude Code must be >={CLAUDE_AGENTS_MINIMUM_VERSION}; "
            "run claude update, start a new session, and rerun project refresh"
        )
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    settings = _settings(config_dir / "settings.json")
    # Managed policy overrides user settings. Platform paths are Claude's
    # documented native managed settings locations, never project config.
    managed_path = (
        (
            Path("/Library/Application Support/ClaudeCode/managed-settings.json")
            if os.uname().sysname == "Darwin"
            else Path("/etc/claude-code/managed-settings.json")
        )
        if os.name != "nt"
        else Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "ClaudeCode/managed-settings.json"
    )
    managed = _settings(managed_path)
    for key in ("pluginConfigs", "enabledPlugins"):
        settings[key] = {**(settings.get(key) or {}), **(managed.get(key) or {})}
    settings.update(
        {
            key: value
            for key, value in managed.items()
            if key not in {"pluginConfigs", "enabledPlugins"}
        }
    )
    assert_claude_loading(root, plans, settings=settings)
    return plans
