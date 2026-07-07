"""Agent/harness hook health checks.

HC functions for hook script executability, the Python check_prerequisites
self-test, and the Claude session-startup hook configuration.

Also owns the shared hook-command parsing helpers used by
``doctor_hc_agents.hc_agent_consistency``: ``_extract_hook_command``,
``_classify_hook_command``, ``_python_module_exists``.

HC functions: HC-hook-executability, HC-self-test, HC-session-startup-hook
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _extract_hook_command(line: str) -> str:
    """Extract a frontmatter ``command:`` value from a single line."""
    if "command:" not in line:
        return ""
    command = line.split("command:", 1)[1].strip()
    if len(command) >= 2 and command[0] == command[-1] and command[0] in {"'", '"'}:
        quote = command[0]
        command = command[1:-1]
        if quote == "'":
            command = command.replace("''", "'")
    return command


def _classify_hook_command(command: str) -> Tuple[str, str]:
    """Classify a hook command as a path, shell literal, or python module."""
    if not command:
        return ("", "")
    try:
        parts = shlex.split(command)
    except ValueError:
        return ("", "")

    while parts and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", parts[0]):
        parts.pop(0)
    if not parts:
        return ("", "")

    head = parts[0]
    if head in {"echo", "sh", "bash"}:
        return ("shell-literal", "")
    if head.startswith("python"):
        if "-m" in parts:
            idx = parts.index("-m")
            if idx + 1 < len(parts):
                return ("python-module", parts[idx + 1])
        return ("python-exec", head)
    return ("path", head.strip("'\""))


def _python_module_exists(module_name: str, repo_root: str) -> bool:
    """Return True when a Python hook module resolves from the repo root."""
    if not module_name:
        return False
    if module_name.startswith("runtime."):
        module_path = Path(repo_root) / Path(*module_name.split("."))
        if module_path.with_suffix(".py").is_file():
            return True
        if module_path.is_dir() and (module_path / "__init__.py").is_file():
            return True
    return importlib.util.find_spec(module_name) is not None


def _hook_command_exists(command_name: str, repo_root: str) -> bool:
    if not command_name:
        return False
    path = Path(command_name)
    if path.is_absolute():
        return path.is_file()
    if "/" not in command_name and shutil.which(command_name):
        return True
    return (Path(repo_root) / command_name).is_file()


def _hook_command_path_for_executable_check(command_name: str, repo_root: str) -> Path | None:
    path = Path(command_name)
    if path.is_absolute():
        return path
    if "/" not in command_name and shutil.which(command_name):
        return None
    return Path(repo_root) / command_name


def hc_hook_executability(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-hook-executability: Hook script executability."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-hook-executability", "Hook script executability", "PASS", "")
        return

    issues: List[str] = []
    agents_dir = Path(repo_root) / ".claude" / "agents"
    if not agents_dir.is_dir():
        rec.record("HC-hook-executability", "Hook script executability", "PASS", "")
        return

    for agent in sorted(agents_dir.glob("yoke-*.md")):
        agent_name = agent.stem
        in_fm = False
        for line in agent.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                else:
                    break
            if "command:" in line:
                command = _extract_hook_command(line)
                kind, target = _classify_hook_command(command)
                if kind in {"", "shell-literal", "python-exec", "python-module"}:
                    continue
                cmd_path = target
                p = _hook_command_path_for_executable_check(cmd_path, repo_root)
                if p is None:
                    continue
                if p.is_file() and not os.access(str(p), os.X_OK):
                    issues.append(f"- {agent_name}: hook script {cmd_path} exists but is not executable")

    if issues:
        rec.record("HC-hook-executability", "Hook script executability", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-hook-executability", "Hook script executability", "PASS", "")


def hc_self_test(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-self-test: Self-test (check_prerequisites Python entrypoint)."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-self-test", "Self-test", "WARN", "Cannot determine repo root")
        return

    entrypoint = Path(repo_root) / "runtime" / "api" / "domain" / "check_prerequisites.py"
    if not entrypoint.is_file():
        rec.record(
            "HC-self-test",
            "Self-test",
            "WARN",
            "check_prerequisites.py not found",
        )
        return

    r = _base._run(
        [sys.executable, "-m", "yoke_core.domain.check_prerequisites", "--repo-root", repo_root],
        timeout=30,
    )
    if r.returncode != 0:
        rec.record("HC-self-test", "Self-test", "FAIL",
                    f"check_prerequisites.py reported failures:\n{r.stdout}\n{r.stderr}")
    else:
        rec.record("HC-self-test", "Self-test", "PASS", "")


def hc_session_startup_hook(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-session-startup-hook: Session startup hook presence and configuration."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-session-startup-hook", "Session startup hook", "PASS", "")
        return

    issues: List[str] = []
    settings_path = Path(repo_root) / ".claude" / "settings.json"
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(errors="replace"))
            hooks = settings.get("hooks", {})
            user_prompt = hooks.get("UserPromptSubmit", [])
            found = False
            if isinstance(user_prompt, list):
                for entry in user_prompt:
                    hooks_list = entry.get("hooks", []) if isinstance(entry, dict) else []
                    for h in hooks_list:
                        cmd = h.get("command", "") if isinstance(h, dict) else ""
                        if "yoke hook evaluate UserPromptSubmit" in cmd:
                            found = True
            if not found:
                issues.append(
                    "- UserPromptSubmit hook missing yoke hook evaluate owner"
                )
        except (json.JSONDecodeError, TypeError):
            issues.append("- .claude/settings.json is not valid JSON")
    else:
        issues.append("- .claude/settings.json not found")

    if issues:
        rec.record("HC-session-startup-hook", "Session startup hook", "WARN", "\n".join(issues))
    else:
        rec.record("HC-session-startup-hook", "Session startup hook", "PASS", "")
