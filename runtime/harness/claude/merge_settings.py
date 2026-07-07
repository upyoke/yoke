"""Merge Yoke claim rules into a Claude Code ``settings.json`` file.

Direct Python owner — callers invoke via ``python3 -m runtime.harness.claude.merge_settings``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


YOKE_RULES = [
    "Bash",
    "Write(**)",
    "Edit(**)",
    "Read(*)",
    "Grep(*)",
    "Glob(*)",
]

YOKE_HOOKS = {
    "UserPromptSubmit": {
        "command": "python3 -m runtime.harness.hook_runner UserPromptSubmit",
        "detect": "runtime.harness.hook_runner UserPromptSubmit",
    },
    "SessionStart": {
        "command": "python3 -m runtime.harness.hook_runner SessionStart",
        "detect": "runtime.harness.hook_runner SessionStart",
    },
    "Stop": {
        "command": "python3 -m runtime.harness.hook_runner Stop",
        "detect": "runtime.harness.hook_runner Stop",
    },
    "SessionEnd": {
        "command": "python3 -m runtime.harness.hook_runner SessionEnd",
        "detect": "runtime.harness.hook_runner SessionEnd",
    },
}


def _resolve_target(raw_target: str) -> Path:
    target = Path(raw_target)
    if target.is_absolute():
        return target
    return (Path.cwd() / target).resolve()


def _load_settings(target: Path) -> dict[str, Any]:
    if not target.is_file():
        return {}
    content = target.read_text(encoding="utf-8")
    if not content.strip():
        return {}
    return json.loads(content)


def _merge_permissions(data: dict[str, Any]) -> None:
    permissions = data.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    existing = set(allow)
    for rule in YOKE_RULES:
        if rule not in existing:
            allow.append(rule)
            existing.add(rule)


def _hook_registered(hooks_list: list[Any], detect: str) -> bool:
    for hook in hooks_list:
        if not isinstance(hook, dict):
            continue
        if "hooks" in hook:
            for inner in hook.get("hooks", []):
                if isinstance(inner, dict) and detect in inner.get("command", ""):
                    return True
        elif detect in hook.get("command", ""):
            return True
    return False


def _merge_hooks(data: dict[str, Any]) -> None:
    hooks = data.setdefault("hooks", {})
    for event_name, hook_def in YOKE_HOOKS.items():
        hooks_list = hooks.setdefault(event_name, [])
        if _hook_registered(hooks_list, hook_def["detect"]):
            continue
        hooks_list.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_def["command"],
                    }
                ]
            }
        )


def merge_settings(target_path: str) -> None:
    target = _resolve_target(target_path)
    data = _load_settings(target)
    _merge_permissions(data)
    _merge_hooks(data)

    temp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


_USAGE = "Usage: python3 -m runtime.harness.claude.merge_settings <path-to-settings.json>"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if len(args) != 1 or not args[0]:
        print(_USAGE, file=sys.stderr)
        return 1
    try:
        merge_settings(args[0])
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {args[0]}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
