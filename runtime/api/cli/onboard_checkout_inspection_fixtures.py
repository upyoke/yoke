"""Repository fixtures for the pre-Apply checkout inspection tests.

One builder for a clean repository and one for a repository that arrived
carrying somebody else's Yoke operating layer — the two states the inspection
has to tell apart, shared by the scan/removal tests and the wizard tests.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from yoke_contracts.project_contract.installed_layer import (
    INSTALLED_LAYER_RECEIPT_REL,
    render_installed_layer_receipt,
)
from yoke_contracts.project_contract.managed_block import render_block

HOOK_COMMAND = "/bin/sh -c 'env YOKE_ROOT=. yoke hook evaluate PreToolUse'"


def write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def clean_repo(tmp_path: Path) -> Path:
    root = tmp_path / "buzz"
    write(root, "README.md", "# Buzz\n")
    write(root, "src/app.py", "print('hi')\n")
    return root


def repo_with_layer(tmp_path: Path, *, release: str = "0.1.1") -> Path:
    root = clean_repo(tmp_path)
    write(root, ".yoke/project.config", "file_line_limit=350\n")
    write(root, ".yoke/docs/index.md", "# Docs\n")
    write(root, ".agents/skills/yoke/dash/SKILL.md", "# dash\n")
    write(root, ".claude/skills/yoke/dash/SKILL.md", "# dash\n")
    write(root, ".claude/agents/yoke-engineer.md", "# engineer\n")
    write(root, ".claude/agents/team-reviewer.md", "# not yoke\n")
    write(root, ".claude/rules/session.md", "# rules\n")
    write(root, INSTALLED_LAYER_RECEIPT_REL, render_installed_layer_receipt(release))
    write(
        root,
        "AGENTS.md",
        "# Buzz rules\n\nOur own text.\n\n" + render_block("Yoke says hello") + "\n",
    )
    write(
        root,
        ".claude/settings.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"hooks": [{"command": HOOK_COMMAND, "type": "command"}]},
                        {"hooks": [{"command": "our-own-hook", "type": "command"}]},
                    ]
                },
                "model": "opus",
            },
            indent=2,
        )
        + "\n",
    )
    return root


def git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        [
            "git", "-C", str(root),
            "-c", "user.email=t@example.com", "-c", "user.name=T",
            "commit", "-q", "-m", "initial",
        ],
        check=True,
    )


__all__ = [
    "HOOK_COMMAND",
    "clean_repo",
    "git_repo",
    "repo_with_layer",
    "write",
]
