"""Check native canonical instruction loading without changing project files."""

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
)
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.harness_cli_manifest import (
    HARNESS_CLI_MANIFESTS,
)
from yoke_contracts import terminal_detached_process


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
    *,
    settings: dict[str, Any],
) -> None:
    """Accept native AGENTS loading or an explicit canonical link/import."""
    plugins = settings.get("enabledPlugins") or {}
    configs = settings.get("pluginConfigs") or {}
    plugin_ids = ("agents-md@builtin", "cc-plugin-agents-md@builtin")
    if any(plugins.get(key) is False for key in plugin_ids):
        _loading_refusal(
            "the built-in AGENTS.md plugin is disabled", "Enable it in /plugin."
        )
    configured = set()
    for key in plugin_ids:
        value = (configs.get(key) or {}).get("options", {}).get("instructionFiles")
        if value is not None:
            if not isinstance(value, str):
                _loading_refusal(
                    "Project instructions must be a supported string",
                    "Set Project instructions to claude-md-and-agents-md in /config.",
                )
            configured.add(value)
    if len(configured) > 1:
        _loading_refusal(
            "the built-in plugin has conflicting configuration entries",
            "Remove the conflicting instructionFiles entry from user or managed settings.",
        )
    mode = next(iter(configured), "claude-md-or-agents-md")
    if mode not in {"claude-md-or-agents-md", "claude-md-and-agents-md"}:
        _loading_refusal(
            f"Project instructions is {mode!r}",
            "Set Project instructions to claude-md-and-agents-md in /config.",
        )
    for pattern in settings.get("claudeMdExcludes") or []:
        if fnmatch.fnmatch(str(root / "AGENTS.md"), pattern) or fnmatch.fnmatch(
            "AGENTS.md", pattern
        ):
            _loading_refusal(
                "claudeMdExcludes excludes the canonical AGENTS.md",
                "Remove the AGENTS.md exclusion from claudeMdExcludes.",
            )
    if mode == "claude-md-and-agents-md":
        return
    canonical = {(root / "AGENTS.md").resolve()}
    primary = main_checkout(root) / "AGENTS.md"
    if primary.is_file():
        canonical.add(primary.resolve())
    for directory in (root, *root.parents):
        for rel in ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"):
            path = directory / rel
            if path.is_file():
                if path.resolve() in canonical or _imports_canonical(path, canonical):
                    continue
                _loading_refusal(
                    f"{path} suppresses native AGENTS.md loading",
                    "Set Project instructions to claude-md-and-agents-md in /config (user or managed settings).",
                )


def _imports_canonical(path: Path, canonical: set[Path]) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProjectInstallError(
            f"instruction_file_unreadable: {path}; repair its encoding or read permissions and rerun refresh"
        ) from exc
    # Claude ignores imports in inline and fenced code.
    text = re.sub(r"```.*?```|~~~.*?~~~|`[^`]*`", "", text, flags=re.S)
    for token in re.findall(r"(?<![\w@])@([^\s`]+)", text):
        if (path.parent / token).resolve() in canonical:
            return True
    return False


def _loading_refusal(detail: str, fix: str) -> None:
    raise ProjectInstallError(
        f"canonical_instructions_not_loaded: {detail}. {fix} "
        "Start a new session and verify AGENTS.md in /memory."
    )


def preflight(root: Path) -> None:
    if (root / "AGENTS.override.md").is_file():
        raise ProjectInstallError(
            "canonical_instructions_not_loaded: AGENTS.override.md suppresses "
            "Codex's canonical AGENTS.md. Preserve its project content in "
            "AGENTS.md outside the Yoke block, then move the override outside "
            "native instruction discovery and rerun refresh."
        )
    for manifest in HARNESS_CLI_MANIFESTS:
        executable = shutil.which(manifest.executable)
        if executable is None:
            continue
        try:
            probe = terminal_detached_process.run(
                [executable, *manifest.version_args],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", probe.stdout)
            observed = (
                tuple(map(int, match.groups()))
                if match and probe.returncode == 0
                else ()
            )
        except (OSError, subprocess.TimeoutExpired):
            observed = ()
        required = tuple(map(int, manifest.minimum_engine_version.split(".")))
        if observed < required:
            raise ProjectInstallError(
                f"instruction_runtime_unsupported: {manifest.executable} must be "
                f">={manifest.minimum_engine_version}; upgrade the native CLI or "
                "embedded desktop engine, start a new session, and rerun refresh"
            )
    if shutil.which("claude") is None:
        return
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    settings = _settings(config_dir / "settings.json")
    # Native plugin enablement and exclusions may come from project/local
    # settings; instructionFiles itself is ignored at those scopes by Claude.
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        scoped = _settings(root / rel)
        settings["enabledPlugins"] = {
            **(settings.get("enabledPlugins") or {}),
            **(scoped.get("enabledPlugins") or {}),
        }
        if "claudeMdExcludes" in scoped:
            settings["claudeMdExcludes"] = scoped["claudeMdExcludes"]
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
    assert_claude_loading(root, settings=settings)
