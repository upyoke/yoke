"""Closed source-checkout programs used by Machine QA fixtures."""

STARTUP_MARKER_ASSERTION_SCRIPT = r"""from pathlib import Path
import sys

marker = sys.argv[1]
expected = int(sys.argv[2])
for raw_path in sys.argv[3:]:
    text = Path(raw_path).read_text(encoding="utf-8")
    if text.count(marker) != expected:
        raise SystemExit(1)
"""


SOURCE_CHECKOUT_ASSERTION_SCRIPT = r"""from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
report_path = Path(sys.argv[2])
expected_origin = sys.argv[3]
expected_branch = sys.argv[4]


def require(condition):
    if not condition:
        raise SystemExit(1)


report = json.loads(report_path.read_text(encoding="utf-8"))
require(report.get("applied") is True)
require((root / "pyproject.toml").is_file())
require((root / "packages").is_dir())
require((root / "runtime").is_dir())
require(
    subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        text=True,
    ).strip()
    == "true"
)
require(
    len(
        subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    )
    >= 7
)
require(
    subprocess.check_output(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        text=True,
    ).strip()
    == expected_origin
)
require(
    subprocess.check_output(
        ["git", "-C", str(root), "branch", "--show-current"],
        text=True,
    ).strip()
    == expected_branch
)
links = (
    ".claude/agents",
    ".claude/rules",
    ".claude/settings.json",
    ".claude/skills/yoke",
    ".codex/agents",
    ".codex/hooks.json",
    "runtime/harness/claude/agents/references/yoke-tester-browser.md",
)
for relative in links:
    require((root / relative).is_symlink())
manifest = json.loads(
    (root / ".yoke" / "install-manifest.json").read_text(encoding="utf-8")
)
require(manifest.get("mode") == "source-link")
manifest_links = manifest.get("symlinks") or {}
for relative in links:
    require(relative in manifest_links)
for hook, marker in (
    ("pre-commit", "yoke-pre-commit"),
    ("post-commit", "yoke-post-commit"),
):
    text = (root / ".git" / "hooks" / hook).read_text(encoding="utf-8")
    require(marker in text)
for relative in links:
    require(os.path.islink(root / relative))
"""


SOURCE_LINK_MODULE = r"""from __future__ import annotations

import json
import os
from pathlib import Path

DEV_SYMLINKS = (
    (".claude/agents", "../runtime/harness/claude/agents"),
    (".claude/rules", "../runtime/harness/claude/rules"),
    (".claude/settings.json", "../runtime/harness/claude/settings.json"),
    (".claude/skills/yoke", "../../.agents/skills/yoke"),
    (".codex/agents", "../runtime/harness/codex/agents"),
    (".codex/hooks.json", "../runtime/harness/codex/hooks.json"),
    (
        "runtime/harness/claude/agents/references/yoke-tester-browser.md",
        "../../../../agents/tester-browser.md",
    ),
)


def _ensure_link(root, relative, target, actions, warnings):
    path = root / relative
    if path.is_symlink():
        if os.readlink(path) == target:
            actions.append(f"Exists: {relative} -> {target}")
        else:
            warnings.append(f"{relative} has an unexpected target")
        return
    if path.exists():
        warnings.append(f"{relative} is not a symlink")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    actions.append(f"Created: {relative} -> {target}")


def _write_hook(root, name, marker, command):
    hook = root / ".git" / "hooks" / name
    if not hook.parent.is_dir():
        return False
    hook.write_text(
        "#!/bin/sh\n"
        f"# {marker} hook installed by `yoke project install`\n"
        f'exec {command} "$@"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return True


def install_source_link(repo_root, operation="install"):
    root = Path(repo_root)
    actions = []
    warnings = []
    for relative, target in DEV_SYMLINKS:
        _ensure_link(root, relative, target, actions, warnings)
    hooks = [
        _write_hook(root, "pre-commit", "yoke-pre-commit", "yoke git pre-commit"),
        _write_hook(root, "post-commit", "yoke-post-commit", "yoke git post-commit"),
    ]
    manifest = {
        "manifest_schema": 1,
        "yoke_version": "source-dev-recipe",
        "mode": "source-link",
        "symlinks": dict(DEV_SYMLINKS),
        "git_hooks": ["pre-commit", "post-commit"],
        "contract_files": {},
    }
    manifest_path = root / ".yoke" / "install-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "operation": operation,
        "mode": "source-link",
        "repo_root": str(root),
        "yoke_version": manifest["yoke_version"],
        "source": "in-checkout",
        "symlinks_created": len(actions),
        "symlinks_ok": 0,
        "hooks_installed_or_updated": sum(bool(item) for item in hooks),
        "actions": actions,
        "contract_files_written": 0,
        "contract_files_existing": 0,
        "contract_files_adopted": 0,
        "manifest": str(manifest_path),
        "machine_config_newly_registered": False,
        "warnings": warnings,
    }
"""


__all__ = [
    "SOURCE_CHECKOUT_ASSERTION_SCRIPT",
    "SOURCE_LINK_MODULE",
    "STARTUP_MARKER_ASSERTION_SCRIPT",
]
